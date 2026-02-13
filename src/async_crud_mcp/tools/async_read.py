"""Async read tool for MCP file operations."""

import os
from datetime import datetime, timezone
from typing import Union

from async_crud_mcp.core import (
    LockManager,
    PathValidationError,
    PathValidator,
    compute_hash,
)
from async_crud_mcp.models import AsyncReadRequest, ErrorCode, ErrorResponse, ReadSuccessResponse


async def async_read(
    request: AsyncReadRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
) -> Union[ReadSuccessResponse, ErrorResponse]:
    """
    Read file content with offset/limit support and hash computation.

    Args:
        request: Read request with path, encoding, offset, and limit
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks

    Returns:
        ReadSuccessResponse with content and metadata, or ErrorResponse on failure
    """
    try:
        # 1. Validate path using PathValidator
        try:
            validated_path = path_validator.validate(request.path)
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

        # 3. Acquire shared read lock
        request_id = await lock_manager.acquire_read(str(validated_path))

        try:
            # 4a. Read file in binary mode, compute hash
            with open(validated_path, 'rb') as f:
                raw_bytes = f.read()

            file_hash = compute_hash(raw_bytes)

            # 4b. Decode content using request encoding
            try:
                content = raw_bytes.decode(request.encoding)
            except (UnicodeDecodeError, LookupError) as e:
                return ErrorResponse(
                    error_code=ErrorCode.ENCODING_ERROR,
                    message=f"Failed to decode file with encoding '{request.encoding}': {e}",
                    path=request.path,
                )

            # 4c. Split into lines, compute total_lines
            lines = content.splitlines(keepends=True)
            total_lines = len(lines)

            # 4d. Apply offset/limit slicing
            offset = request.offset
            limit = request.limit

            if limit is not None:
                sliced = lines[offset:offset + limit]
            else:
                sliced = lines[offset:]

            # 4e. Join sliced lines back to content string
            content = ''.join(sliced)
            lines_returned = len(sliced)

            # 4f. Build ReadSuccessResponse
            return ReadSuccessResponse(
                content=content,
                hash=file_hash,
                total_lines=total_lines,
                offset=offset,
                limit=limit,
                lines_returned=lines_returned,
                encoding=request.encoding,
                path=str(validated_path),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            # 5. Release read lock
            await lock_manager.release_read(str(validated_path), request_id)

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during read: {e}",
            path=request.path,
        )
