"""Async append tool for MCP file operations."""

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
)
from async_crud_mcp.models import (
    AppendSuccessResponse,
    AsyncAppendRequest,
    ErrorCode,
    ErrorResponse,
)


async def async_append(
    request: AsyncAppendRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
) -> Union[AppendSuccessResponse, ErrorResponse]:
    """
    Append content to file with optional file creation and separator support.

    Args:
        request: Append request with path, content, and options
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes

    Returns:
        AppendSuccessResponse on success, or ErrorResponse on failure
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

        # 2. Check file existence
        file_exists = os.path.exists(validated_path)
        if not file_exists and not request.create_if_missing:
            return ErrorResponse(
                error_code=ErrorCode.FILE_NOT_FOUND,
                message=f"File not found: {request.path}",
                path=request.path,
            )

        # 3. If file doesn't exist and create_if_missing=true, create it
        if not file_exists and request.create_if_missing:
            # Create parent directories if requested
            if request.create_dirs:
                parent_dir = os.path.dirname(str(validated_path))
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

            # Create empty file
            try:
                with open(validated_path, 'wb') as f:
                    pass  # Create empty file
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.WRITE_ERROR,
                    message=f"Failed to create file: {e}",
                    path=request.path,
                )

        # 4. Acquire exclusive write lock
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
            # 5. Check if file is empty (to skip separator on first append)
            file_size_before = os.path.getsize(validated_path)
            is_empty = file_size_before == 0

            # 6. Encode separator + content to bytes
            try:
                # Skip separator if file is empty
                if is_empty or not request.separator:
                    content_to_append = request.content
                else:
                    content_to_append = request.separator + request.content

                encoded_bytes = content_to_append.encode(request.encoding)
            except (UnicodeEncodeError, LookupError) as e:
                return ErrorResponse(
                    error_code=ErrorCode.ENCODING_ERROR,
                    message=f"Failed to encode content with encoding '{request.encoding}': {e}",
                    path=request.path,
                )

            # 7. Open file in append binary mode and write
            try:
                with open(validated_path, 'ab') as f:
                    f.write(encoded_bytes)
                    os.fsync(f.fileno())
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.WRITE_ERROR,
                    message=f"Failed to append to file: {e}",
                    path=request.path,
                )

            # 8. Read full file to compute new hash
            try:
                with open(validated_path, 'rb') as f:
                    full_content = f.read()
                new_hash = compute_hash(full_content)
                total_size = len(full_content)
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.SERVER_ERROR,
                    message=f"Failed to read file for hash computation: {e}",
                    path=request.path,
                )

            # 9. Update HashRegistry
            hash_registry.update(str(validated_path), new_hash)

            # 10. Build AppendSuccessResponse
            bytes_appended = len(encoded_bytes)

            return AppendSuccessResponse(
                path=str(validated_path),
                hash=new_hash,
                bytes_appended=bytes_appended,
                total_size_bytes=total_size,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            # 11. Release write lock
            await lock_manager.release_write(str(validated_path), request_id)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during append: {e}",
            path=request.path,
        )
