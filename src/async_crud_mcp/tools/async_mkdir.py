"""Async mkdir tool for creating directories with safety guards."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Union

from async_crud_mcp.config import PROJECT_CONFIG_DIR
from async_crud_mcp.core import AccessDeniedError, PathValidationError, PathValidator
from async_crud_mcp.models.requests import AsyncMkdirRequest
from async_crud_mcp.models.responses import (
    ErrorCode,
    ErrorResponse,
    MkdirSuccessResponse,
)

if TYPE_CHECKING:
    from async_crud_mcp.core.recycle_bin import RecycleBin

from async_crud_mcp.core.recycle_bin import RecycleBinError


async def async_mkdir(
    request: AsyncMkdirRequest,
    path_validator: PathValidator,
    recycle_bin: RecycleBin | None = None,
) -> Union[MkdirSuccessResponse, ErrorResponse]:
    """Create a directory with safety guards.

    If the target exists and is non-empty and force=False, returns an error.
    If force=True and the directory is non-empty, the existing contents are
    recycled before recreating the directory.

    Args:
        request: Mkdir request with path, parents, and force flags.
        path_validator: PathValidator instance for path validation.
        recycle_bin: Optional RecycleBin for safe deletion of existing contents.

    Returns:
        MkdirSuccessResponse on success, or ErrorResponse on failure.
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

        # 2. Safety guard: if target exists and is non-empty, require force=True
        if os.path.exists(validated_path):
            if not os.path.isdir(validated_path):
                return ErrorResponse(
                    error_code=ErrorCode.FILE_EXISTS,
                    message=f"Path exists and is not a directory: {request.path}",
                    path=request.path,
                )
            if os.listdir(validated_path) and not request.force:
                return ErrorResponse(
                    error_code=ErrorCode.FILE_EXISTS,
                    message=f"Directory exists and is not empty: {request.path}. Use force=True to proceed.",
                    path=request.path,
                )

            if os.listdir(validated_path) and request.force:
                # Non-empty directory with force=True: recycle contents first
                dir_path = Path(validated_path)

                # Self-protection: refuse to recycle config/recycle directories
                if recycle_bin is not None and recycle_bin.is_protected_path(dir_path):
                    return ErrorResponse(
                        error_code=ErrorCode.ACCESS_DENIED,
                        message="Cannot force-overwrite internal configuration directory",
                        path=request.path,
                    )

                # Also protect the config dir (.async-crud-mcp/)
                try:
                    if dir_path.resolve().name == PROJECT_CONFIG_DIR:
                        return ErrorResponse(
                            error_code=ErrorCode.ACCESS_DENIED,
                            message="Cannot force-overwrite internal configuration directory",
                            path=request.path,
                        )
                except OSError:
                    pass

                if recycle_bin is None or not recycle_bin.enabled:
                    return ErrorResponse(
                        error_code=ErrorCode.SERVER_ERROR,
                        message="Cannot force-overwrite non-empty directory without recycle bin",
                        path=request.path,
                    )

                # Recycle the existing directory
                try:
                    entry_count = len(os.listdir(validated_path))
                    dir_hash = f"dir:{entry_count}_entries"
                    await recycle_bin.recycle(dir_path, dir_hash, reason="mkdir-force")
                except RecycleBinError as e:
                    return ErrorResponse(
                        error_code=ErrorCode.SERVER_ERROR,
                        message=f"Failed to recycle existing directory: {e}",
                        path=request.path,
                    )

                # Recreate the directory
                os.makedirs(validated_path, exist_ok=True)
                return MkdirSuccessResponse(path=str(validated_path), created=True)

            # Directory exists and is empty (or force=True with empty dir)
            return MkdirSuccessResponse(path=str(validated_path), created=False)

        # 3. Create directory
        os.makedirs(validated_path, exist_ok=True) if request.parents else os.mkdir(validated_path)

        return MkdirSuccessResponse(path=str(validated_path), created=True)

    except FileNotFoundError as e:
        return ErrorResponse(
            error_code=ErrorCode.DIR_NOT_FOUND,
            message=f"Parent directory not found (use parents=True): {e}",
            path=request.path,
        )
    except OSError as e:
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Failed to create directory: {e}",
            path=request.path,
        )
    except Exception as e:
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during mkdir: {e}",
            path=request.path,
        )
