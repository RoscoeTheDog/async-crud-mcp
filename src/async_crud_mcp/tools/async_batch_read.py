"""Async batch read tool for MCP file operations."""

from async_crud_mcp.core import ContentScanner, LockManager, PathValidator
from async_crud_mcp.models import (
    AsyncBatchReadRequest,
    AsyncReadRequest,
    BatchReadResponse,
    BatchSummary,
    ErrorCode,
    ErrorResponse,
)
from async_crud_mcp.tools.async_read import async_read


async def async_batch_read(
    request: AsyncBatchReadRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    content_scanner: ContentScanner | None = None,
) -> BatchReadResponse:
    """
    Read multiple files in a single batch operation.

    Operations are processed sequentially (not transactional). Partial failures
    are reported per-file in the results array.

    Args:
        request: Batch read request with list of files to read
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        content_scanner: Optional ContentScanner for sensitive data detection

    Returns:
        BatchReadResponse with per-file results and summary
    """
    try:
        results = []
        succeeded = 0
        failed = 0

        # Process each file sequentially
        for item in request.files:
            # Convert BatchReadItem to AsyncReadRequest
            read_request = AsyncReadRequest(
                path=item.path,
                offset=item.offset,
                limit=item.limit,
                encoding=item.encoding,
            )

            # Call single-file async_read
            result = await async_read(read_request, path_validator, lock_manager, content_scanner)

            # Collect result and update counters
            results.append(result)
            if result.status == "ok":
                succeeded += 1
            else:
                failed += 1

        # Build summary
        summary = BatchSummary(
            total=len(request.files),
            succeeded=succeeded,
            failed=failed,
            contention=0,
        )

        return BatchReadResponse(
            results=results,
            summary=summary,
        )

    except Exception as e:
        # Catastrophic error - return all items as failed
        from typing import Union

        error_results: list[Union[ErrorResponse, object]] = [
            ErrorResponse(
                error_code=ErrorCode.SERVER_ERROR,
                message=f"Batch operation failed: {e}",
                path=item.path,
            )
            for item in request.files
        ]

        summary = BatchSummary(
            total=len(request.files),
            succeeded=0,
            failed=len(request.files),
            contention=0,
        )

        return BatchReadResponse(
            results=error_results,  # type: ignore[arg-type]
            summary=summary,
        )
