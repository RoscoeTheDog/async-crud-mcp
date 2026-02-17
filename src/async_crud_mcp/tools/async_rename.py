"""Async rename tool for MCP file operations."""

import os
from datetime import datetime, timezone
from typing import Union

from async_crud_mcp.core import (
    AccessDeniedError,
    HashRegistry,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    compute_hash,
    safe_rename,
)
from async_crud_mcp.core.diff_engine import compute_diff
from async_crud_mcp.models import (
    AsyncRenameRequest,
    ContentionResponse,
    ErrorCode,
    ErrorResponse,
    RenameSuccessResponse,
)


async def async_rename(
    request: AsyncRenameRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
) -> Union[RenameSuccessResponse, ContentionResponse, ErrorResponse]:
    """
    Rename file with dual-lock and optional hash-based contention detection.

    Args:
        request: Rename request with old_path, new_path, and options
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes

    Returns:
        RenameSuccessResponse on success, ContentionResponse on hash mismatch,
        or ErrorResponse on failure
    """
    try:
        # 1. Validate both paths with operation-specific access checks
        try:
            validated_old = path_validator.validate_operation(request.old_path, "delete")
        except AccessDeniedError as e:
            return ErrorResponse(
                error_code=ErrorCode.ACCESS_DENIED,
                message=str(e),
                path=request.old_path,
            )
        except PathValidationError as e:
            return ErrorResponse(
                error_code=ErrorCode.PATH_OUTSIDE_BASE,
                message=str(e),
                path=request.old_path,
            )

        try:
            validated_new = path_validator.validate_operation(request.new_path, "write")
        except AccessDeniedError as e:
            return ErrorResponse(
                error_code=ErrorCode.ACCESS_DENIED,
                message=str(e),
                path=request.new_path,
            )
        except PathValidationError as e:
            return ErrorResponse(
                error_code=ErrorCode.PATH_OUTSIDE_BASE,
                message=str(e),
                path=request.new_path,
            )

        # 2. Check old_path exists
        if not os.path.exists(validated_old):
            return ErrorResponse(
                error_code=ErrorCode.FILE_NOT_FOUND,
                message=f"Source file not found: {request.old_path}",
                path=request.old_path,
            )

        # 3. If overwrite=false, check new_path does NOT exist
        if not request.overwrite and os.path.exists(validated_new):
            return ErrorResponse(
                error_code=ErrorCode.FILE_EXISTS,
                message=f"Destination file already exists: {request.new_path}",
                path=request.new_path,
            )

        # 4. Acquire dual write locks in alphabetical order
        try:
            request_id_old, request_id_new = await lock_manager.acquire_dual_write(
                str(validated_old),
                str(validated_new),
                timeout=request.timeout
            )
        except LockTimeout:
            return ErrorResponse(
                error_code=ErrorCode.LOCK_TIMEOUT,
                message=f"Failed to acquire locks within {request.timeout}s",
                path=request.old_path,
            )

        try:
            # 5. If expected_hash provided, verify it matches
            if request.expected_hash is not None:
                # Read file to compute current hash
                try:
                    with open(validated_old, 'rb') as f:
                        current_bytes = f.read()
                    current_hash = compute_hash(current_bytes)
                except OSError as e:
                    return ErrorResponse(
                        error_code=ErrorCode.SERVER_ERROR,
                        message=f"Failed to read file for hash verification: {e}",
                        path=request.old_path,
                    )

                # Check for hash mismatch
                if current_hash != request.expected_hash:
                    # Decode current content for diff
                    try:
                        current_content = current_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        current_content = current_bytes.decode('utf-8', errors='replace')

                    # Compute diff (we don't have expected content, just show current)
                    diff = compute_diff(
                        old_content="",
                        new_content=current_content,
                        diff_format=request.diff_format,
                    )

                    return ContentionResponse(
                        current_hash=current_hash,
                        expected_hash=request.expected_hash,
                        diff=diff,
                        path=str(validated_old),
                        message=f"File has been modified (expected hash: {request.expected_hash}, current hash: {current_hash})",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )

            # 6. Create parent directories if requested
            if request.create_dirs:
                parent_dir = os.path.dirname(str(validated_new))
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

            # 7. Perform rename with cross-filesystem fallback
            try:
                cross_filesystem = safe_rename(str(validated_old), str(validated_new))
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.RENAME_ERROR,
                    message=f"Failed to rename file: {e}",
                    path=request.old_path,
                )

            # 8. Compute hash of renamed file (same as old file)
            with open(validated_new, 'rb') as f:
                file_bytes = f.read()
            file_hash = compute_hash(file_bytes)

            # 9. Update HashRegistry
            hash_registry.remove(str(validated_old))
            hash_registry.update(str(validated_new), file_hash)

            # 10. Build RenameSuccessResponse
            return RenameSuccessResponse(
                old_path=str(validated_old),
                new_path=str(validated_new),
                hash=file_hash,
                cross_filesystem=cross_filesystem,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            # 11. Release both locks
            await lock_manager.release_write(str(validated_old), request_id_old)
            await lock_manager.release_write(str(validated_new), request_id_new)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during rename: {e}",
            path=request.old_path,
        )
