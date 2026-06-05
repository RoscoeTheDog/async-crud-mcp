"""Shell execution tool for MCP operations.

Executes shell commands with deny-pattern validation, environment sanitization,
and optional background execution. Uses asyncio subprocesses with process
containment (Job Objects on Windows, RLIMIT_NPROC on POSIX) to prevent fork
bombs and runaway process creation.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from async_crud_mcp.core import process_guard
from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.core.content_scanner import ContentScanner
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
    RedactionEntry,
)


async def async_exec(
    request: ExecRequest,
    shell_config: ShellConfig,
    shell_provider: ShellProvider,
    shell_validator: ShellValidator,
    background_registry: BackgroundTaskRegistry,
    project_root: Path | None = None,
    content_scanner: ContentScanner | None = None,
) -> ExecSuccessResponse | ExecDeniedResponse | ExecBackgroundResponse | ErrorResponse:
    """Execute a shell command with policy enforcement.

    Args:
        request: Exec request with command, timeout, cwd, env, background flag.
        shell_config: Shell configuration (enabled, deny patterns, etc.).
        shell_provider: Cross-platform shell detection.
        shell_validator: Command deny-pattern validator.
        background_registry: Registry for background tasks.
        project_root: Active project root for cwd fallback.
        content_scanner: Optional scanner to redact sensitive data from output.

    Returns:
        Appropriate response model based on execution result.
    """
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
        # Strip sensitive vars here too -- env_inherit=False must not let
        # request.env smuggle in LD_PRELOAD / secret vars unstripped.
        for key in shell_config.env_strip:
            env.pop(key, None)

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
            request.command, exec_args, cwd, env, background_registry
        )
    else:
        result = await _exec_foreground(
            request.command, exec_args, cwd, env, timeout,
            process_limit=shell_config.process_limit,
            max_output_size=shell_config.max_output_size_bytes,
            content_scanner=content_scanner,
        )
        if timeout_clamped and isinstance(result, ExecSuccessResponse):
            # Re-create with timeout_applied since model is frozen
            result = ExecSuccessResponse(
                command=result.command,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                timeout_applied=timeout,
                stdout_redactions=result.stdout_redactions,
                stderr_redactions=result.stderr_redactions,
            )
        return result


async def _exec_foreground(
    command: str,
    exec_args: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    process_limit: int = 50,
    max_output_size: int = 52_428_800,
    content_scanner: ContentScanner | None = None,
) -> ExecSuccessResponse | ErrorResponse:
    """Run command in foreground with timeout and process containment.

    Uses asyncio subprocess with Job Object (Windows) or RLIMIT_NPROC
    (POSIX) to contain fork bombs and runaway process creation.
    """
    start = time.monotonic()
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    timed_out = False
    output_truncated = False
    job = None

    extra_kwargs: dict = {}
    if sys.platform == "win32":
        job = process_guard.create_job(process_limit)
        extra_kwargs["creationflags"] = (
            process_guard.CREATE_SUSPENDED | process_guard.CREATE_NO_WINDOW
        )
    else:
        extra_kwargs["preexec_fn"] = process_guard.make_preexec_fn(process_limit)
        extra_kwargs["start_new_session"] = True

    exit_code = -1
    try:
        proc = await asyncio.create_subprocess_exec(
            *exec_args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **extra_kwargs,
        )

        if job is not None:
            process_guard.assign_to_job(job, proc.pid)
            process_guard.resume_process(proc.pid)

        async def _drain_stdout() -> None:
            nonlocal output_truncated
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                if len(stdout_buf) + len(stderr_buf) < max_output_size:
                    stdout_buf.extend(chunk)
                else:
                    # Keep draining (discard) so the process does not block on a
                    # full pipe, but stop growing memory.
                    output_truncated = True

        async def _drain_stderr() -> None:
            nonlocal output_truncated
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(8192)
                if not chunk:
                    break
                if len(stdout_buf) + len(stderr_buf) < max_output_size:
                    stderr_buf.extend(chunk)
                else:
                    output_truncated = True

        try:
            await asyncio.wait_for(
                asyncio.gather(_drain_stdout(), _drain_stderr(), proc.wait()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            if job is not None:
                process_guard.terminate_job(job)
            else:
                _kill_process_tree(proc.pid)
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except (OSError, ProcessLookupError):
                    pass

        exit_code = proc.returncode if proc.returncode is not None else -1
    finally:
        if job is not None:
            process_guard.close_job(job)

    duration_ms = int((time.monotonic() - start) * 1000)

    if timed_out:
        return ErrorResponse(
            error_code=ErrorCode.COMMAND_TIMEOUT,
            message=f"Command timed out after {timeout}s.",
            details={"command": command, "timeout": timeout, "duration_ms": duration_ms},
        )

    stdout_text = stdout_buf.decode("utf-8", errors="replace")
    stderr_text = stderr_buf.decode("utf-8", errors="replace")

    if output_truncated:
        stdout_text += (
            f"\n<output truncated: combined stdout+stderr exceeded {max_output_size} bytes>"
        )

    # Redact sensitive data from output before returning to agent
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

    return ExecSuccessResponse(
        command=command,
        stdout=stdout_text,
        stderr=stderr_text,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout_redactions=stdout_redaction_entries,
        stderr_redactions=stderr_redaction_entries,
    )


def _kill_process_tree(pid: int) -> None:
    """Terminate a process and its entire child tree by PID (fallback).

    On Windows, the primary kill path is via Job Object termination in
    the process guard. This function serves as a fallback when the job
    handle is unavailable. On POSIX with start_new_session=True, sends
    SIGTERM to the entire process group.
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
    )
