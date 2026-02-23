"""Async update tool for MCP file operations with contention detection."""

import os
from datetime import datetime, timezone
from typing import Optional, Union

from async_crud_mcp.core import (
    AccessDeniedError,
    ContentScanner,
    HashRegistry,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    atomic_write,
    compute_hash,
)
from async_crud_mcp.core.diff_engine import compute_diff
from async_crud_mcp.models import (
    AsyncUpdateRequest,
    ContentionResponse,
    ErrorCode,
    ErrorResponse,
    PatchConflict,
    RedactionEntry,
    UpdateSuccessResponse,
)


async def async_update(
    request: AsyncUpdateRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
    content_scanner: Optional[ContentScanner] = None,
    max_file_size_bytes: int = 0,
) -> Union[UpdateSuccessResponse, ContentionResponse, ErrorResponse]:
    """
    Update existing file atomically with hash-based contention detection.

    Args:
        request: Update request with path, expected_hash, and either content or patches
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes
        content_scanner: Optional ContentScanner for scanning contention diffs.
            When provided and a hash mismatch triggers a contention response,
            the current file content is scanned. If sensitive content is detected,
            the diff is redacted from the response to prevent data leakage.

    Returns:
        UpdateSuccessResponse on success, ContentionResponse on hash mismatch,
        or ErrorResponse on failure
    """
    try:
        # Defense in depth: Verify content or patches is provided
        if request.content is None and request.patches is None:
            return ErrorResponse(
                error_code=ErrorCode.CONTENT_OR_PATCHES_REQUIRED,
                message="Exactly one of content or patches must be provided",
                path=request.path,
            )

        # 1. Validate path and access policy
        try:
            validated_path = path_validator.validate_operation(request.path, "update")
        except AccessDeniedError as e:
            return ErrorResponse(
                error_code=ErrorCode.ACCESS_DENIED,
                message=str(e),
                path=request.path,
            )
        except PathValidationError as e:
            return ErrorResponse(
                error_code=ErrorCode.PATH_OUTSIDE_BASE,
                message=str(e),
                path=request.path,
            )

        # 2. Check file exists (before acquiring lock)
        if not os.path.exists(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.FILE_NOT_FOUND,
                message=f"File does not exist: {request.path}",
                path=request.path,
            )

        # 3. Acquire exclusive write lock
        try:
            request_id = await lock_manager.acquire_write(
                str(validated_path),
                timeout=request.timeout
            )
        except LockTimeout:
            return ErrorResponse(
                error_code=ErrorCode.LOCK_TIMEOUT,
                message=f"Failed to acquire write lock within {request.timeout}s",
                path=request.path,
            )

        try:
            # 4. Read current file content and compute hash
            try:
                with open(validated_path, "rb") as f:
                    current_bytes = f.read()
                current_hash = compute_hash(current_bytes)
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.SERVER_ERROR,
                    message=f"Failed to read file for hash check: {e}",
                    path=request.path,
                )

            # 5. Check hash match
            if current_hash != request.expected_hash:
                # Hash mismatch - prepare contention response
                try:
                    current_content = current_bytes.decode(request.encoding)
                except UnicodeDecodeError as e:
                    return ErrorResponse(
                        error_code=ErrorCode.ENCODING_ERROR,
                        message=f"Failed to decode file with encoding '{request.encoding}': {e}",
                        path=request.path,
                    )

                # Content-scan: redact sensitive spans in current content
                # before computing the diff, so placeholders appear in the diff
                # instead of raw secrets.
                redacted_result = None
                redaction_entries = None
                diff_content = current_content  # default: use original

                if content_scanner is not None:
                    redacted_result = content_scanner.redact(
                        current_content, str(validated_path)
                    )
                    if redacted_result.has_redactions:
                        diff_content = redacted_result.content
                        redaction_entries = [
                            RedactionEntry(
                                id=r.id,
                                rule_name=r.rule_name,
                                line=r.line,
                                col_start=r.col_start,
                                original_length=r.original_length,
                            )
                            for r in redacted_result.redactions
                        ]

                # Compute diff for contention response
                if request.content is not None:
                    # Content mode: diff between what agent wanted to write
                    # and current content (possibly redacted)
                    diff = compute_diff(
                        request.content,
                        diff_content,
                        diff_format=request.diff_format,
                        context_lines=3,
                    )
                    patches_applicable = None
                    conflicts = None
                    non_conflicting_patches = None
                else:
                    # Patch mode: check applicability against ORIGINAL content
                    # (patches reference original text), but diff uses redacted content.
                    assert request.patches is not None

                    applied_content = current_content
                    patch_conflicts: list[PatchConflict] = []
                    non_conflicting_indices: list[int] = []

                    # Check patch applicability against original content
                    for idx, patch in enumerate(request.patches):
                        if patch.old_string in applied_content:
                            non_conflicting_indices.append(idx)
                            applied_content = applied_content.replace(
                                patch.old_string,
                                patch.new_string,
                                1  # Replace first occurrence only
                            )
                        else:
                            patch_conflicts.append(
                                PatchConflict(
                                    patch_index=idx,
                                    reason="old_string not found in current file content"
                                )
                            )

                    patches_applicable = len(patch_conflicts) == 0
                    conflicts = patch_conflicts if patch_conflicts else None
                    non_conflicting_patches = non_conflicting_indices if non_conflicting_indices else None

                    # For the diff, apply applicable patches to the redacted
                    # content so secrets don't leak through the "from" side.
                    diff_applied = diff_content
                    if diff_content != current_content:
                        # Content was redacted -- re-apply patches to redacted text
                        for idx in (non_conflicting_indices or []):
                            patch = request.patches[idx]
                            if patch.old_string in diff_applied:
                                diff_applied = diff_applied.replace(
                                    patch.old_string, patch.new_string, 1
                                )

                    else:
                        diff_applied = applied_content

                    # Diff shows expected (with patches applied) vs current
                    # (possibly redacted)
                    diff = compute_diff(
                        diff_applied,
                        diff_content,
                        diff_format=request.diff_format,
                        context_lines=3,
                    )

                is_redacted = redacted_result is not None and redacted_result.has_redactions

                return ContentionResponse(
                    path=str(validated_path),
                    expected_hash=request.expected_hash,
                    current_hash=current_hash,
                    message=(
                        f"File has been modified since hash "
                        f"{request.expected_hash[:16]}... "
                        f"and contains sensitive content"
                    ) if is_redacted else (
                        f"File has been modified since hash "
                        f"{request.expected_hash[:16]}..."
                    ),
                    diff=diff,
                    redacted=is_redacted,
                    redacted_pattern=(
                        redacted_result.redactions[0].rule_name
                        if is_redacted else None
                    ),
                    redacted_hint=(
                        "Diff contains <<REDACTED:rule:N>> placeholders. "
                        "Use the redactions array for span details. "
                        "Re-read the file if you need the original values."
                    ) if is_redacted else None,
                    redactions=redaction_entries,
                    patches_applicable=patches_applicable,
                    conflicts=conflicts,
                    non_conflicting_patches=non_conflicting_patches,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            # 6. Hash matches - proceed with update
            previous_hash = current_hash

            if request.content is not None:
                # Content mode: full replacement
                try:
                    new_content = request.content
                    encoded_bytes = new_content.encode(request.encoding)
                except (UnicodeEncodeError, LookupError) as e:
                    return ErrorResponse(
                        error_code=ErrorCode.ENCODING_ERROR,
                        message=f"Failed to encode content with encoding '{request.encoding}': {e}",
                        path=request.path,
                    )
            else:
                # Patch mode: apply patches sequentially
                # Type guard: patches is not None here (validated by model)
                assert request.patches is not None
                patches_to_apply = request.patches

                try:
                    current_content = current_bytes.decode(request.encoding)
                except UnicodeDecodeError as e:
                    return ErrorResponse(
                        error_code=ErrorCode.ENCODING_ERROR,
                        message=f"Failed to decode file with encoding '{request.encoding}': {e}",
                        path=request.path,
                    )

                new_content = current_content
                for idx, patch in enumerate(patches_to_apply):
                    if patch.old_string not in new_content:
                        return ErrorResponse(
                            error_code=ErrorCode.INVALID_PATCH,
                            message=f"Patch {idx}: old_string not found in file content: {patch.old_string[:50]}...",
                            path=request.path,
                        )
                    # Replace first occurrence only
                    new_content = new_content.replace(patch.old_string, patch.new_string, 1)

                try:
                    encoded_bytes = new_content.encode(request.encoding)
                except (UnicodeEncodeError, LookupError) as e:
                    return ErrorResponse(
                        error_code=ErrorCode.ENCODING_ERROR,
                        message=f"Failed to encode patched content with encoding '{request.encoding}': {e}",
                        path=request.path,
                    )

            # 6b. Check file size limit
            if max_file_size_bytes > 0 and len(encoded_bytes) > max_file_size_bytes:
                return ErrorResponse(
                    error_code=ErrorCode.FILE_TOO_LARGE,
                    message=f"Content size {len(encoded_bytes)} bytes exceeds max_file_size_bytes ({max_file_size_bytes})",
                    path=request.path,
                )

            # 7. Write updated content atomically
            try:
                atomic_write(str(validated_path), encoded_bytes)
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.WRITE_ERROR,
                    message=f"Failed to write file: {e}",
                    path=request.path,
                )

            # 8. Compute new hash
            new_hash = compute_hash(encoded_bytes)

            # 9. Update HashRegistry
            hash_registry.update(str(validated_path), new_hash)

            # 10. Build UpdateSuccessResponse
            bytes_written = len(encoded_bytes)

            return UpdateSuccessResponse(
                path=str(validated_path),
                previous_hash=previous_hash,
                hash=new_hash,
                bytes_written=bytes_written,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            # 11. Release write lock
            await lock_manager.release_write(str(validated_path), request_id)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during update: {e}",
            path=request.path,
        )
