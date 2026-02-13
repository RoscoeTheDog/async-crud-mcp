"""Async batch update tool for MCP file operations."""

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator
from async_crud_mcp.models import (
    AsyncBatchUpdateRequest,
    AsyncUpdateRequest,
    BatchSummary,
    BatchUpdateResponse,
    ErrorCode,
    ErrorResponse,
)
from async_crud_mcp.tools.async_update import async_update


async def async_batch_update(
    request: AsyncBatchUpdateRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
) -> BatchUpdateResponse:
    """
    Update multiple existing files in a single batch operation.

    Operations are processed sequentially (not transactional). Partial failures
    and contentions are reported per-file in the results array.

    Args:
        request: Batch update request with list of files to update
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for coordinating locks
        hash_registry: HashRegistry instance for tracking file hashes

    Returns:
        BatchUpdateResponse with per-file results and summary
    """
    try:
        results = []
        succeeded = 0
        failed = 0
        contention = 0

        # Process each file sequentially
        for item in request.files:
            # Convert BatchUpdateItem to AsyncUpdateRequest
            update_request = AsyncUpdateRequest(
                path=item.path,
                expected_hash=item.expected_hash,
                content=item.content,
                patches=item.patches,
                encoding=item.encoding,
                timeout=request.timeout,
                diff_format=request.diff_format,
            )

            # Call single-file async_update
            result = await async_update(update_request, path_validator, lock_manager, hash_registry)

            # Collect result and update counters
            results.append(result)
            if result.status == "ok":
                succeeded += 1
            elif result.status == "contention":
                contention += 1
            else:
                failed += 1

        # Build summary
        summary = BatchSummary(
            total=len(request.files),
            succeeded=succeeded,
            failed=failed,
            contention=contention,
        )

        return BatchUpdateResponse(
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

        return BatchUpdateResponse(
            results=error_results,  # type: ignore[arg-type]
            summary=summary,
        )
