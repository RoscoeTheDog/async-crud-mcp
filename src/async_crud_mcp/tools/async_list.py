"""Async list tool for directory listing with glob filtering."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from async_crud_mcp.core import AccessDeniedError, HashRegistry, PathValidationError, PathValidator
from async_crud_mcp.models import (
    AsyncListRequest,
    DirectoryEntry,
    ErrorCode,
    ErrorResponse,
    ListSuccessResponse,
)


async def async_list(
    request: AsyncListRequest,
    path_validator: PathValidator,
    hash_registry: HashRegistry,
) -> Union[ListSuccessResponse, ErrorResponse]:
    """
    List directory contents with glob filtering and optional hash attachment.

    Args:
        request: List request with path, pattern, recursive, and include_hashes
        path_validator: PathValidator instance for path validation
        hash_registry: HashRegistry instance for hash lookups

    Returns:
        ListSuccessResponse with directory entries, or ErrorResponse on failure
    """
    try:
        # 1. Validate path and access policy
        try:
            validated_path = path_validator.validate_operation(request.path, "list")
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

        # 2. Check directory exists
        if not os.path.exists(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.DIR_NOT_FOUND,
                message=f"Directory not found: {request.path}",
                path=request.path,
            )

        if not os.path.isdir(validated_path):
            return ErrorResponse(
                error_code=ErrorCode.DIR_NOT_FOUND,
                message=f"Path is not a directory: {request.path}",
                path=request.path,
            )

        # 3. List directory contents based on recursive flag
        entries: list[DirectoryEntry] = []
        base_path = Path(validated_path)

        if request.recursive:
            # Use pathlib.rglob for recursive matching (supports ** syntax)
            for match in sorted(base_path.rglob(request.pattern)):
                rel_path = str(match.relative_to(base_path))

                try:
                    stat_info = match.stat()
                    modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()
                except OSError:
                    modified = None

                if match.is_dir():
                    entries.append(
                        DirectoryEntry(
                            name=rel_path,
                            type="directory",
                            size_bytes=None,
                            modified=modified,
                            hash=None,
                        )
                    )
                else:
                    try:
                        size_bytes = stat_info.st_size
                    except (OSError, UnboundLocalError):
                        size_bytes = None

                    file_hash = None
                    if request.include_hashes:
                        file_hash = hash_registry.get(str(match))

                    entries.append(
                        DirectoryEntry(
                            name=rel_path,
                            type="file",
                            size_bytes=size_bytes,
                            modified=modified,
                            hash=file_hash,
                        )
                    )

        else:
            # Use pathlib.glob for non-recursive matching
            try:
                for match in sorted(base_path.glob(request.pattern)):
                    rel_path = match.name

                    try:
                        stat_info = match.stat(follow_symlinks=False)
                        modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()
                    except OSError:
                        modified = None
                        stat_info = None

                    if match.is_dir():
                        entries.append(
                            DirectoryEntry(
                                name=rel_path,
                                type="directory",
                                size_bytes=None,
                                modified=modified,
                                hash=None,
                            )
                        )
                    else:
                        size_bytes = stat_info.st_size if stat_info else None

                        file_hash = None
                        if request.include_hashes:
                            file_hash = hash_registry.get(str(match))

                        entries.append(
                            DirectoryEntry(
                                name=rel_path,
                                type="file",
                                size_bytes=size_bytes,
                                modified=modified,
                                hash=file_hash,
                            )
                        )
            except OSError as e:
                return ErrorResponse(
                    error_code=ErrorCode.SERVER_ERROR,
                    message=f"Failed to list directory: {e}",
                    path=request.path,
                )

        # 4. Build and return ListSuccessResponse
        return ListSuccessResponse(
            path=str(validated_path),
            entries=entries,
        )

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during list: {e}",
            path=request.path,
        )
