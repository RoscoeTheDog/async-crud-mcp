"""Async mkdir tool for creating directories with safety guards."""

import os
from typing import Union

from async_crud_mcp.core import AccessDeniedError, PathValidationError, PathValidator
from async_crud_mcp.models.requests import AsyncMkdirRequest
from async_crud_mcp.models.responses import (
    ErrorCode,
    ErrorResponse,
    MkdirSuccessResponse,
)


async def async_mkdir(
    request: AsyncMkdirRequest,
    path_validator: PathValidator,
) -> Union[MkdirSuccessResponse, ErrorResponse]:
    """Create a directory with safety guards.

    If the target exists and is non-empty and force=False, returns an error.

    Args:
        request: Mkdir request with path, parents, and force flags.
        path_validator: PathValidator instance for path validation.

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
            # Directory exists (empty or force=True)
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
