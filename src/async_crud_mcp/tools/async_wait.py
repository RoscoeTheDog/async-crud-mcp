"""Wait/sleep tool for MCP operations."""

import time

import anyio

from async_crud_mcp.core.background_tasks import BackgroundTask, BackgroundTaskRegistry
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.models.requests import WaitRequest
from async_crud_mcp.models.responses import (
    ErrorCode, ErrorResponse, RedactionEntry,
    TaskResultPayload, TaskWaitResult, WaitResponse,
)


def _build_task_result(
    task: BackgroundTask,
    content_scanner: ContentScanner | None,
) -> TaskWaitResult:
    """Build a TaskWaitResult with optional redaction for a completed task."""
    stdout_text = task.stdout
    stderr_text = task.stderr
    stdout_redactions: list[RedactionEntry] | None = None
    stderr_redactions: list[RedactionEntry] | None = None

    if content_scanner is not None:
        stdout_r = content_scanner.redact(stdout_text, path="<exec:stdout>")
        stderr_r = content_scanner.redact(stderr_text, path="<exec:stderr>")
        stdout_text = stdout_r.content
        stderr_text = stderr_r.content
        if stdout_r.has_redactions:
            stdout_redactions = [
                RedactionEntry(id=r.id, rule_name=r.rule_name, line=r.line,
                               col_start=r.col_start, original_length=r.original_length)
                for r in stdout_r.redactions
            ]
        if stderr_r.has_redactions:
            stderr_redactions = [
                RedactionEntry(id=r.id, rule_name=r.rule_name, line=r.line,
                               col_start=r.col_start, original_length=r.original_length)
                for r in stderr_r.redactions
            ]

    return TaskWaitResult(
        task_id=task.task_id,
        task_result=TaskResultPayload(
            exit_code=task.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=task.duration_ms,
        ),
        stdout_redactions=stdout_redactions,
        stderr_redactions=stderr_redactions,
    )


async def async_wait(
    request: WaitRequest,
    background_registry: BackgroundTaskRegistry,
    content_scanner: ContentScanner | None = None,
) -> WaitResponse | ErrorResponse:
    """Wait for a duration or background task(s) completion."""

    # Normalize task_id to list or None
    task_ids: list[str] | None = None
    if isinstance(request.task_id, str):
        task_ids = [request.task_id]
    elif isinstance(request.task_id, list) and len(request.task_id) > 0:
        task_ids = list(dict.fromkeys(request.task_id))  # deduplicate, preserve order

    if task_ids is None:
        # Simple sleep
        start = time.monotonic()
        await anyio.sleep(request.seconds)
        return WaitResponse(
            waited_seconds=round(time.monotonic() - start, 3),
            reason=f"Slept for {request.seconds}s",
        )

    # Validate all IDs exist
    not_found = [tid for tid in task_ids if background_registry.get(tid) is None]
    if not_found:
        return ErrorResponse(
            error_code=ErrorCode.TASK_NOT_FOUND,
            message=f"Background task(s) not found: {', '.join(not_found)}",
            details={"task_ids": not_found},
        )

    wait_timeout = request.seconds if request.seconds > 0 else 30.0
    start = time.monotonic()
    completed = await background_registry.wait_for_any(task_ids, wait_timeout)
    waited = time.monotonic() - start

    if not completed:
        return WaitResponse(
            waited_seconds=round(waited, 3),
            reason=f"All {len(task_ids)} tasks still running after {round(waited, 1)}s wait",
            task_status="all_running",
        )

    results = [_build_task_result(t, content_scanner) for t in completed]
    return WaitResponse(
        waited_seconds=round(waited, 3),
        reason=f"{len(results)}/{len(task_ids)} tasks completed",
        task_status="completed",
        completed_tasks=results,
    )
