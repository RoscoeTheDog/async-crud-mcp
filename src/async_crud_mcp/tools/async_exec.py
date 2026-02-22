"""Shell execution tool for MCP operations.

Executes shell commands with deny-pattern validation, environment sanitization,
and optional background execution via anyio.
"""

import os
import signal
import subprocess
import sys
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

    # 2. Check empty/whitespace-only command
    if not request.command.strip():
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_DENIED,
            message="Command cannot be empty or whitespace-only.",
        )

    # 2b. Check for null bytes
    if "\x00" in request.command:
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_DENIED,
            message="Command contains null bytes.",
        )

    # 3. Check command length
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
    timeout_clamped = request.timeout != timeout

    # 5. Resolve cwd
    cwd: str | None = None
    if request.cwd:
        resolved = Path(request.cwd).resolve()
        if project_root and not str(resolved).startswith(str(project_root.resolve())):
            return ErrorResponse(
                error_code=ErrorCode.PATH_OUTSIDE_BASE,
                message=f"cwd is outside project root: {request.cwd}",
            )
        cwd = str(resolved)
    elif shell_config.cwd_override:
        cwd = shell_config.cwd_override
    elif project_root:
        cwd = str(project_root)

    # 6. Build environment
    env: dict[str, str] | None = None
    if shell_config.env_inherit:
        env = dict(os.environ)
        if request.env:
            env.update(request.env)
        # Strip sensitive vars AFTER merge to prevent re-injection
        for key in shell_config.env_strip:
            env.pop(key, None)
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
        result = await _exec_foreground(
            request.command, exec_args, cwd, env, timeout, timestamp
        )
        if timeout_clamped and isinstance(result, ExecSuccessResponse):
            # Re-create with timeout_applied since model is frozen
            result = ExecSuccessResponse(
                command=result.command,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                timestamp=result.timestamp,
                timeout_applied=timeout,
            )
        return result


async def _exec_foreground(
    command: str,
    exec_args: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    timestamp: str,
) -> ExecSuccessResponse | ErrorResponse:
    """Run command in foreground with timeout.

    Uses open_process with explicit terminate/kill to ensure the child
    process is actually stopped when the timeout expires, rather than
    relying on cancel-scope propagation which may not kill the child
    on all platforms.
    """
    start = time.monotonic()
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    timed_out = False

    # Use start_new_session on POSIX so we can kill the entire process group
    kwargs: dict = {}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    exit_code = -1
    async with await anyio.open_process(
        exec_args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    ) as process:

        async def _drain_stdout() -> None:
            if process.stdout:
                async for chunk in process.stdout:
                    stdout_buf.extend(chunk)

        async def _drain_stderr() -> None:
            if process.stderr:
                async for chunk in process.stderr:
                    stderr_buf.extend(chunk)

        try:
            with anyio.fail_after(timeout):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(_drain_stdout)
                    tg.start_soon(_drain_stderr)
                await process.wait()
        except TimeoutError:
            timed_out = True
            # Kill the process tree, not just the shell
            _kill_process_tree(process.pid)
            # Give it a moment to die, then force kill
            with anyio.move_on_after(2.0):
                await process.wait()
            if process.returncode is None:
                process.kill()

        exit_code = process.returncode if process.returncode is not None else -1

    duration_ms = int((time.monotonic() - start) * 1000)

    if timed_out:
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_TIMEOUT,
            message=f"Command timed out after {timeout}s.",
            details={"command": command, "timeout": timeout, "duration_ms": duration_ms},
        )

    return ExecSuccessResponse(
        command=command,
        stdout=stdout_buf.decode("utf-8", errors="replace"),
        stderr=stderr_buf.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        duration_ms=duration_ms,
        timestamp=timestamp,
    )


def _kill_process_tree(pid: int) -> None:
    """Terminate a process and its entire child tree by PID.

    On POSIX with start_new_session=True, sends SIGTERM to the entire
    process group. On Windows, uses ``taskkill /T /F`` which recursively
    kills the process tree (children, grandchildren, etc.). Falls back to
    os.kill if taskkill is not available.
    """
    if sys.platform != "win32":
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass  # Process already exited
    else:
        try:
            # taskkill /T kills child processes, /F forces termination
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            # taskkill not available (unlikely on Windows), fall back
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        except (OSError, subprocess.TimeoutExpired):
            pass  # Process already exited or taskkill hung


async def _exec_background(
    command: str,
    exec_args: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    registry: BackgroundTaskRegistry,
    timestamp: str,
) -> ExecBackgroundResponse:
    """Launch command in background and return immediately.

    Uses the registry's server-owned task group for structured concurrency,
    so background tasks are properly cancelled on server shutdown.
    """
    task = registry.create_task(command)
    await registry.spawn_background(task, exec_args, cwd=cwd, env=env)

    return ExecBackgroundResponse(
        task_id=task.task_id,
        command=command,
        timestamp=timestamp,
    )
