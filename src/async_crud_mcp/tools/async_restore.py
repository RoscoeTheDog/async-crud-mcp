"""Async restore tool for recovering files from the recycle bin."""

from pathlib import Path
from typing import Union

from async_crud_mcp.core import PathValidator, RecycleBin, RecycleBinError
from async_crud_mcp.models import (
    AsyncRestoreRequest,
    ErrorCode,
    ErrorResponse,
    RestoreSuccessResponse,
)


async def async_restore(
    request: AsyncRestoreRequest,
    path_validator: PathValidator,
    recycle_bin: RecycleBin,
) -> Union[RestoreSuccessResponse, ErrorResponse]:
    """
    Restore a file from the recycle bin.

    Args:
        request: Restore request with recycle_name and optional destination
        path_validator: PathValidator instance for destination validation
        recycle_bin: RecycleBin instance managing recycled files

    Returns:
        RestoreSuccessResponse on success, or ErrorResponse on failure
    """
    try:
        # Validate destination path if provided
        destination = None
        if request.destination is not None:
            try:
                validated = path_validator.validate_operation(request.destination, "write")
                destination = Path(validated)
            except Exception as e:
                return ErrorResponse(
                    error_code=ErrorCode.PATH_OUTSIDE_BASE,
                    message=f"Destination path validation failed: {e}",
                    path=request.destination,
                )

        result = await recycle_bin.restore(
            recycle_name=request.recycle_name,
            destination=destination,
            force=request.force,
            timeout=request.timeout,
            path_validator=path_validator,
        )

        return RestoreSuccessResponse(
            restored_path=result.restored_path,
            original_path=result.original_path,
            recycle_name=result.recycle_name,
        )

    except RecycleBinError as e:
        return ErrorResponse(
            error_code=ErrorCode.FILE_NOT_FOUND,
            message=str(e),
            path=request.recycle_name,
        )
    except Exception as e:
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during restore: {e}",
            path=request.recycle_name,
        )
