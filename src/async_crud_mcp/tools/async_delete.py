"""Async delete tool for MCP file operations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Union

from async_crud_mcp.core import (
    AccessDeniedError,
    HashRegistry,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    compute_hash,
)
from async_crud_mcp.core.diff_engine import compute_diff
from async_crud_mcp.models import (
    AsyncDeleteRequest,
    ContentionResponse,
    DeleteSuccessResponse,
    ErrorCode,
    ErrorResponse,
)

if TYPE_CHECKING:
    from async_crud_mcp.core.recycle_bin import RecycleBin

from async_crud_mcp.core.recycle_bin import RecycleBinError


async def async_delete(
    request: AsyncDeleteRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
    recycle_bin: RecycleBin | None = None,
) -> Union[DeleteSuccessResponse, ContentionResponse, ErrorResponse]:
    """
    Delete file with optional hash-based contention detection.

    Args:
        request: Delete request with path and optional expected_hash
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes
        recycle_bin: Optional RecycleBin for safe deletion (move instead of unlink)

    Returns:
        DeleteSuccessResponse on success, ContentionResponse on hash mismatch,
        or ErrorResponse on failure
    """
    try:
        # 1. Validate path and access policy
        try:
            validated_path = path_validator.validate_operation(request.path, "delete")
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

        # 2. Check file exists
        if not os.path.exists(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.FILE_NOT_FOUND,
                message=f"File not found: {request.path}",
                path=request.path,
            )

        # 2b. async_delete is file-only. Reject directories with a distinct code
        # (separation of concerns) instead of a misleading OS permission error;
        # directory trees are recycled via async_mkdir(force=True).
        if os.path.isdir(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.IS_A_DIRECTORY,
                message=(
                    f"Path is a directory, not a file: {request.path}. "
                    f"Use async_mkdir(force=True) to recycle a directory tree."
                ),
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
            # 4. If expected_hash provided, verify it matches
            if request.expected_hash is not None:
                # Read file to compute current hash
                try:
                    with open(validated_path, 'rb') as f:
                        current_bytes = f.read()
                    current_hash = compute_hash(current_bytes)
                except OSError as e:
                    return ErrorResponse(
                        error_code=ErrorCode.SERVER_ERROR,
                        message=f"Failed to read file for hash verification: {e}",
                        path=request.path,
                    )

                # Check for hash mismatch
                if current_hash != request.expected_hash:
                    # Determine modification source
                    registry_hash = hash_registry.get(str(validated_path))
                    if registry_hash is None:
                        modified_by = "unknown"
                    elif registry_hash == current_hash:
                        modified_by = "agent"
                    else:
                        modified_by = "external"

                    # Decode current content for diff
                    try:
                        current_content = current_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        current_content = current_bytes.decode('utf-8', errors='replace')

                    # Compute diff: expected was empty (delete intent), current is file content
                    diff = compute_diff(
                        old_content="",  # Expected state after delete
                        new_content=current_content,  # Current state
                        diff_format=request.diff_format,
                    )

                    return ContentionResponse(
                        current_hash=current_hash,
                        expected_hash=request.expected_hash,
                        modified_by=modified_by,
                        diff=diff,
                        path=str(validated_path),
                        message=f"File has been modified ({modified_by}) (expected hash: {request.expected_hash}, current hash: {current_hash})",
                    )

            # 5. Delete the file (safe-delete via recycle bin when available)
            try:
                # Read file hash before deletion for response
                with open(validated_path, 'rb') as f:
                    deleted_bytes = f.read()
                deleted_hash = compute_hash(deleted_bytes)

                recycled = False
                recycle_name = None
                if recycle_bin is not None and recycle_bin.enabled:
                    from pathlib import Path as _Path
                    entry = await recycle_bin.recycle(_Path(validated_path), deleted_hash)
                    recycled = True
                    recycle_name = entry.recycle_name
                else:
                    os.unlink(validated_path)
            except (OSError, RecycleBinError) as e:
                return ErrorResponse(
                    error_code=ErrorCode.DELETE_ERROR,
                    message=f"Failed to delete file: {e}",
                    path=request.path,
                )

            # 6. Remove from HashRegistry
            hash_registry.remove(str(validated_path))

            # 7. Build DeleteSuccessResponse
            return DeleteSuccessResponse(
                path=str(validated_path),
                deleted_hash=deleted_hash,
                recycled=recycled,
                recycle_name=recycle_name,
            )

        finally:
            # 8. Release write lock
            await lock_manager.release_write(str(validated_path), request_id)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during delete: {e}",
            path=request.path,
        )
