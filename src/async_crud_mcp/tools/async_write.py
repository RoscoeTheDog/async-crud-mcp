"""Async write tool for MCP file operations."""

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
    atomic_write,
    compute_hash,
)
from async_crud_mcp.models import AsyncWriteRequest, ErrorCode, ErrorResponse, WriteSuccessResponse


async def async_write(
    request: AsyncWriteRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
) -> Union[WriteSuccessResponse, ErrorResponse]:
    """
    Write new file atomically with exclusive locking.

    Args:
        request: Write request with path, content, encoding, and options
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes

    Returns:
        WriteSuccessResponse with metadata, or ErrorResponse on failure
    """
    try:
        # 1. Validate path and access policy
        try:
            validated_path = path_validator.validate_operation(request.path, "write")
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

        # 2. Check file does NOT exist (before acquiring lock)
        if os.path.exists(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.FILE_EXISTS,
                message=f"File already exists: {request.path}",
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
            # Second existence check inside lock to handle races
            if os.path.exists(validated_path):
                return ErrorResponse(
                    error_code=ErrorCode.FILE_EXISTS,
                    message=f"File already exists: {request.path}",
                    path=request.path,
                )

            # 4a. Create parent directories if requested
            if request.create_dirs:
                parent_dir = os.path.dirname(str(validated_path))
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

            # 4b. Encode content to bytes
            try:
                encoded_bytes = request.content.encode(request.encoding)
            except (UnicodeEncodeError, LookupError) as e:
                return ErrorResponse(
                    error_code=ErrorCode.ENCODING_ERROR,
                    message=f"Failed to encode content with encoding '{request.encoding}': {e}",
                    path=request.path,
                )

            # 4c. Call atomic_write
            try:
                atomic_write(str(validated_path), encoded_bytes)
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.WRITE_ERROR,
                    message=f"Failed to write file: {e}",
                    path=request.path,
                )

            # 4d. Compute hash
            file_hash = compute_hash(encoded_bytes)

            # 4e. Update HashRegistry
            hash_registry.update(str(validated_path), file_hash)

            # 4f. Build WriteSuccessResponse
            bytes_written = len(encoded_bytes)

            return WriteSuccessResponse(
                path=str(validated_path),
                hash=file_hash,
                bytes_written=bytes_written,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            # 5. Release write lock
            await lock_manager.release_write(str(validated_path), request_id)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during write: {e}",
            path=request.path,
        )
