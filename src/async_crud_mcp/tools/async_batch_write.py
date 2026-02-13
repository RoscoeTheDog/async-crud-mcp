"""Async batch write tool for MCP file operations."""

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator
from async_crud_mcp.models import (
    AsyncBatchWriteRequest,
    AsyncWriteRequest,
    BatchSummary,
    BatchWriteResponse,
    ErrorCode,
    ErrorResponse,
)
from async_crud_mcp.tools.async_write import async_write


async def async_batch_write(
    request: AsyncBatchWriteRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
) -> BatchWriteResponse:
    """
    Write multiple new files in a single batch operation.

    Operations are processed sequentially (not transactional). Partial failures
    are reported per-file in the results array.

    Args:
        request: Batch write request with list of files to write
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes

    Returns:
        BatchWriteResponse with per-file results and summary
    """
    try:
        results = []
        succeeded = 0
        failed = 0

        # Process each file sequentially
        for item in request.files:
            # Convert BatchWriteItem to AsyncWriteRequest
            write_request = AsyncWriteRequest(
                path=item.path,
                content=item.content,
                encoding=item.encoding,
                create_dirs=item.create_dirs,
                timeout=request.timeout,
            )

            # Call single-file async_write
            result = await async_write(write_request, path_validator, lock_manager, hash_registry)

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

        return BatchWriteResponse(
            results=results,
            summary=summary,
        )

    except Exception as e:
        # Catastrophic error - return all items as failed
        error_results = [
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

        return BatchWriteResponse(
            results=error_results,  # type: ignore[arg-type]
            summary=summary,
        )
