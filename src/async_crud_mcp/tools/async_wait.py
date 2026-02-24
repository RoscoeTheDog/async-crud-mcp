"""Wait/sleep tool for MCP operations.

Supports both simple sleep and waiting for background task completion.
"""

import time

import anyio

from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.models.requests import WaitRequest
from async_crud_mcp.models.responses import ErrorCode, ErrorResponse, RedactionEntry, TaskResultPayload, WaitResponse


async def async_wait(
    request: WaitRequest,
    background_registry: BackgroundTaskRegistry,
    content_scanner: ContentScanner | None = None,
) -> WaitResponse | ErrorResponse:
    """Wait for a duration or background task completion.

    Args:
        request: Wait request with seconds and/or task_id.
        background_registry: Registry of background tasks.
        content_scanner: Optional scanner to redact sensitive data from task output.

    Returns:
        WaitResponse or ErrorResponse.
    """
    if request.task_id is not None:
        return await _wait_for_task(
            request.task_id, request.seconds, background_registry,
            content_scanner=content_scanner,
        )

    # Simple sleep
    start = time.monotonic()
    await anyio.sleep(request.seconds)
    waited = time.monotonic() - start

    return WaitResponse(
        waited_seconds=round(waited, 3),
        reason=f"Slept for {request.seconds}s",
    )


async def _wait_for_task(
    task_id: str,
    timeout: float,
    registry: BackgroundTaskRegistry,
    content_scanner: ContentScanner | None = None,
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
        stdout_text = task.stdout
        stderr_text = task.stderr
        stdout_redaction_entries: list[RedactionEntry] | None = None
        stderr_redaction_entries: list[RedactionEntry] | None = None
        if content_scanner is not None:
            stdout_redacted = content_scanner.redact(stdout_text, path="<exec:stdout>")
            stderr_redacted = content_scanner.redact(stderr_text, path="<exec:stderr>")
            stdout_text = stdout_redacted.content
            stderr_text = stderr_redacted.content
            if stdout_redacted.has_redactions:
                stdout_redaction_entries = [
                    RedactionEntry(
                        id=r.id, rule_name=r.rule_name, line=r.line,
                        col_start=r.col_start, original_length=r.original_length,
                    )
                    for r in stdout_redacted.redactions
                ]
            if stderr_redacted.has_redactions:
                stderr_redaction_entries = [
                    RedactionEntry(
                        id=r.id, rule_name=r.rule_name, line=r.line,
                        col_start=r.col_start, original_length=r.original_length,
                    )
                    for r in stderr_redacted.redactions
                ]
        return WaitResponse(
            waited_seconds=0.0,
            reason="Task already completed",
            task_result=TaskResultPayload(
                exit_code=task.exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_ms=task.duration_ms,
            ),
            task_status="completed",
            stdout_redactions=stdout_redaction_entries,
            stderr_redactions=stderr_redaction_entries,
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
            task_status="running",
        )

    stdout_text = result_task.stdout
    stderr_text = result_task.stderr
    stdout_redaction_entries2: list[RedactionEntry] | None = None
    stderr_redaction_entries2: list[RedactionEntry] | None = None
    if content_scanner is not None:
        stdout_redacted = content_scanner.redact(stdout_text, path="<exec:stdout>")
        stderr_redacted = content_scanner.redact(stderr_text, path="<exec:stderr>")
        stdout_text = stdout_redacted.content
        stderr_text = stderr_redacted.content
        if stdout_redacted.has_redactions:
            stdout_redaction_entries2 = [
                RedactionEntry(
                    id=r.id, rule_name=r.rule_name, line=r.line,
                    col_start=r.col_start, original_length=r.original_length,
                )
                for r in stdout_redacted.redactions
            ]
        if stderr_redacted.has_redactions:
            stderr_redaction_entries2 = [
                RedactionEntry(
                    id=r.id, rule_name=r.rule_name, line=r.line,
                    col_start=r.col_start, original_length=r.original_length,
                )
                for r in stderr_redacted.redactions
            ]

    return WaitResponse(
        waited_seconds=round(waited, 3),
        reason="Task completed",
        task_result=TaskResultPayload(
            exit_code=result_task.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=result_task.duration_ms,
        ),
        task_status="completed",
        stdout_redactions=stdout_redaction_entries2,
        stderr_redactions=stderr_redaction_entries2,
    )
