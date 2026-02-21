"""Shell execution tool for MCP operations.

Executes shell commands with deny-pattern validation, environment sanitization,
and optional background execution via anyio.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import anyio

from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.core.shell_provider import ShellProvider
from async_crud_mcp.core.shell_validator import ShellValidator
from async_crud_mcp.config import ShellConfig
from async_crud_mcp.models.requests import ExecRequest
from async_crud_mcp.models.responses import (
    ErrorCode,
    ErrorResponse,
    ExecBackgroundResponse,
    ExecDeniedResponse,
    ExecSuccessResponse,
)


async def async_exec(
    request: ExecRequest,
    shell_config: ShellConfig,
    shell_provider: ShellProvider,
    shell_validator: ShellValidator,
    background_registry: BackgroundTaskRegistry,
    project_root: Path | None = None,
) -> ExecSuccessResponse | ExecDeniedResponse | ExecBackgroundResponse | ErrorResponse:
    """Execute a shell command with policy enforcement.

    Args:
        request: Exec request with command, timeout, cwd, env, background flag.
        shell_config: Shell configuration (enabled, deny patterns, etc.).
        shell_provider: Cross-platform shell detection.
        shell_validator: Command deny-pattern validator.
        background_registry: Registry for background tasks.
        project_root: Active project root for cwd fallback.

    Returns:
        Appropriate response model based on execution result.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Check shell enabled
    if not shell_config.enabled:
        return ErrorResponse(
            error_code=ErrorCode.SHELL_DISABLED,
            message="Shell execution is disabled in configuration.",
        )

    # 2. Check command length
    if len(request.command) > shell_config.max_command_length:
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_DENIED,
            message=f"Command exceeds max length ({len(request.command)} > {shell_config.max_command_length}).",
        )

    # 3. Validate against deny patterns
    allowed, matched_pattern, reason = shell_validator.validate(request.command)
    if not allowed:
        return ExecDeniedResponse(
            command=request.command,
            matched_pattern=matched_pattern,
            reason=reason,
            timestamp=timestamp,
        )

    # 4. Clamp timeout
    timeout = max(0.1, min(request.timeout, shell_config.timeout_max))

    # 5. Resolve cwd
    cwd: str | None = None
    if request.cwd:
        cwd = request.cwd
    elif shell_config.cwd_override:
        cwd = shell_config.cwd_override
    elif project_root:
        cwd = str(project_root)

    # 6. Build environment
    env: dict[str, str] | None = None
    if shell_config.env_inherit:
        env = dict(os.environ)
        # Strip sensitive vars
        for key in shell_config.env_strip:
            env.pop(key, None)
        # Merge user-supplied env
        if request.env:
            env.update(request.env)
    elif request.env:
        env = dict(request.env)

    # 7. Build exec args
    try:
        exec_args = shell_provider.build_exec_args(request.command)
    except Exception as e:
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Shell not available: {e}",
        )

    # 8. Execute
    if request.background:
        return await _exec_background(
            request.command, exec_args, cwd, env, background_registry, timestamp
        )
    else:
        return await _exec_foreground(
            request.command, exec_args, cwd, env, timeout, timestamp
        )


async def _exec_foreground(
    command: str,
    exec_args: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    timestamp: str,
) -> ExecSuccessResponse | ErrorResponse:
    """Run command in foreground with timeout."""
    start = time.monotonic()
    try:
        with anyio.fail_after(timeout):
            result = await anyio.run_process(
                exec_args,
                cwd=cwd,
                env=env,
                check=False,
            )
    except TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_TIMEOUT,
            message=f"Command timed out after {timeout}s.",
            details={"command": command, "timeout": timeout, "duration_ms": duration_ms},
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    return ExecSuccessResponse(
        command=command,
        stdout=result.stdout.decode("utf-8", errors="replace") if result.stdout else "",
        stderr=result.stderr.decode("utf-8", errors="replace") if result.stderr else "",
        exit_code=result.returncode,
        duration_ms=duration_ms,
        timestamp=timestamp,
    )


async def _exec_background(
    command: str,
    exec_args: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    registry: BackgroundTaskRegistry,
    timestamp: str,
) -> ExecBackgroundResponse:
    """Launch command in background and return immediately."""
    task = registry.create_task(command)

    # Start background runner in a detached task group
    # We use anyio's task group to ensure proper structured concurrency
    async def _run() -> None:
        await registry.run_background(task, exec_args, cwd=cwd, env=env)

    # We need to start the background task without blocking.
    # Use a standalone task via the current event loop.
    import asyncio
    loop = asyncio.get_running_loop()
    loop.create_task(_run())

    return ExecBackgroundResponse(
        task_id=task.task_id,
        command=command,
        timestamp=timestamp,
    )
