"""Wait/sleep tool for MCP operations.

Supports both simple sleep and waiting for background task completion.
"""

import time
from datetime import datetime, timezone

import anyio

from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.models.requests import WaitRequest
from async_crud_mcp.models.responses import ErrorCode, ErrorResponse, WaitResponse


async def async_wait(
    request: WaitRequest,
    background_registry: BackgroundTaskRegistry,
) -> WaitResponse | ErrorResponse:
    """Wait for a duration or background task completion.

    Args:
        request: Wait request with seconds and/or task_id.
        background_registry: Registry of background tasks.

    Returns:
        WaitResponse or ErrorResponse.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if request.task_id is not None:
        return await _wait_for_task(
            request.task_id, request.seconds, background_registry, timestamp
        )

    # Simple sleep
    start = time.monotonic()
    await anyio.sleep(request.seconds)
    waited = time.monotonic() - start

    return WaitResponse(
        waited_seconds=round(waited, 3),
        reason=f"Slept for {request.seconds}s",
        timestamp=timestamp,
    )


async def _wait_for_task(
    task_id: str,
    timeout: float,
    registry: BackgroundTaskRegistry,
    timestamp: str,
) -> WaitResponse | ErrorResponse:
    """Wait for a specific background task to complete."""
    task = registry.get(task_id)
    if task is None:
        return ErrorResponse(
            error_code=ErrorCode.TASK_NOT_FOUND,
            message=f"Background task not found: {task_id}",
            details={"task_id": task_id},
        )

    if task.is_complete:
        return WaitResponse(
            waited_seconds=0.0,
            reason="Task already completed",
            task_result={
                "task_id": task.task_id,
                "command": task.command,
                "exit_code": task.exit_code,
                "stdout": task.stdout,
                "stderr": task.stderr,
                "duration_ms": task.duration_ms,
            },
            timestamp=timestamp,
        )

    # Use timeout from request.seconds, default to 30s if 0
    wait_timeout = timeout if timeout > 0 else 30.0
    start = time.monotonic()
    result_task = await registry.wait_for(task_id, wait_timeout)
    waited = time.monotonic() - start

    if result_task is None or not result_task.is_complete:
        return WaitResponse(
            waited_seconds=round(waited, 3),
            reason=f"Task {task_id} still running after {round(waited, 1)}s wait",
            task_result={"task_id": task_id, "status": "running"},
            timestamp=timestamp,
        )

    return WaitResponse(
        waited_seconds=round(waited, 3),
        reason="Task completed",
        task_result={
            "task_id": result_task.task_id,
            "command": result_task.command,
            "exit_code": result_task.exit_code,
            "stdout": result_task.stdout,
            "stderr": result_task.stderr,
            "duration_ms": result_task.duration_ms,
        },
        timestamp=timestamp,
    )
