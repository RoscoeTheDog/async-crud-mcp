"""Async list tool for directory listing with glob filtering."""

import fnmatch
import os
from datetime import datetime, timezone
from typing import Union

from async_crud_mcp.core import HashRegistry, PathValidationError, PathValidator
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
        # 1. Validate path using PathValidator
        try:
            validated_path = path_validator.validate(request.path)
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

        if request.recursive:
            # Recursive listing using os.walk
            for root, dirs, files in os.walk(validated_path):
                # Calculate relative path from base directory
                rel_root = os.path.relpath(root, validated_path)
                if rel_root == ".":
                    rel_root = ""

                # Process directories
                for dir_name in dirs:
                    if request.pattern != "*" and not fnmatch.fnmatch(dir_name, request.pattern):
                        continue

                    rel_path = os.path.join(rel_root, dir_name) if rel_root else dir_name
                    full_path = os.path.join(root, dir_name)

                    try:
                        stat_info = os.stat(full_path)
                        modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()
                    except OSError:
                        modified = None

                    entries.append(
                        DirectoryEntry(
                            name=rel_path,
                            type="directory",
                            size_bytes=None,
                            modified=modified,
                            hash=None,
                        )
                    )

                # Process files
                for file_name in files:
                    if request.pattern != "*" and not fnmatch.fnmatch(file_name, request.pattern):
                        continue

                    rel_path = os.path.join(rel_root, file_name) if rel_root else file_name
                    full_path = os.path.join(root, file_name)

                    try:
                        stat_info = os.stat(full_path)
                        size_bytes = stat_info.st_size
                        modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()
                    except OSError:
                        size_bytes = None
                        modified = None

                    # Get hash if requested
                    file_hash = None
                    if request.include_hashes:
                        file_hash = hash_registry.get(full_path)

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
            # Non-recursive listing using os.scandir
            try:
                with os.scandir(validated_path) as it:
                    for entry in it:
                        # Apply glob filter
                        if request.pattern != "*" and not fnmatch.fnmatch(entry.name, request.pattern):
                            continue

                        try:
                            stat_info = entry.stat(follow_symlinks=False)
                            is_dir = entry.is_dir(follow_symlinks=False)

                            if is_dir:
                                modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()
                                entries.append(
                                    DirectoryEntry(
                                        name=entry.name,
                                        type="directory",
                                        size_bytes=None,
                                        modified=modified,
                                        hash=None,
                                    )
                                )
                            else:
                                size_bytes = stat_info.st_size
                                modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat()

                                # Get hash if requested
                                file_hash = None
                                if request.include_hashes:
                                    file_hash = hash_registry.get(entry.path)

                                entries.append(
                                    DirectoryEntry(
                                        name=entry.name,
                                        type="file",
                                        size_bytes=size_bytes,
                                        modified=modified,
                                        hash=file_hash,
                                    )
                                )
                        except OSError:
                            # Skip entries we can't stat
                            continue
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
            total_entries=len(entries),
            pattern=request.pattern,
            recursive=request.recursive,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during list: {e}",
            path=request.path,
        )
