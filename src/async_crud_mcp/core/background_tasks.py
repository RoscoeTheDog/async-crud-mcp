"""Background task registry for long-running shell commands.

Uses asyncio subprocesses for reliable background execution with streaming
output and no pipe deadlocks.

Tracks asyncio tasks for proper cancellation on shutdown. Completed
tasks are reaped after a configurable TTL to prevent unbounded memory growth.
"""

import asyncio
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field


# How long completed tasks stay in registry before reaping (seconds)
_COMPLETED_TASK_TTL = 300.0  # 5 minutes


@dataclass
class BackgroundTask:
    """A background shell command with captured output."""

    task_id: str
    command: str
    started_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None
    exit_code: int | None = None
    stdout_buffer: bytearray = field(default_factory=bytearray)
    stderr_buffer: bytearray = field(default_factory=bytearray)
    _completion_event: asyncio.Event = field(default_factory=asyncio.Event)
    _process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _asyncio_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def is_complete(self) -> bool:
        return self.exit_code is not None

    @property
    def duration_ms(self) -> int | None:
        if self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at) * 1000)

    @property
    def stdout(self) -> str:
        return self.stdout_buffer.decode("utf-8", errors="replace")

    @property
    def stderr(self) -> str:
        return self.stderr_buffer.decode("utf-8", errors="replace")


class BackgroundTaskRegistry:
    """Manages background shell tasks with output capture.

    Uses asyncio.create_task for launching background work (required for
    non-blocking dispatch in request-response servers), while tracking
    tasks for proper cleanup on shutdown.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._reaper_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the reaper loop. Call once during server startup."""
        if self._reaper_task is None:
            self._reaper_task = asyncio.create_task(self._reap_loop())

    async def shutdown(self) -> None:
        """Cancel all background tasks and kill running processes.

        Called during server shutdown to prevent orphaned subprocesses.
        """
        # Stop the reaper
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            self._reaper_task = None

        # Kill all active processes and cancel their asyncio tasks
        for task in list(self._tasks.values()):
            if not task.is_complete:
                # Kill the process tree first
                if task._process is not None and task._process.returncode is None:
                    _kill_process_tree(task._process.pid)
                    try:
                        task._process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                # Cancel the asyncio task
                if task._asyncio_task is not None and not task._asyncio_task.done():
                    task._asyncio_task.cancel()

    def create_task(self, command: str) -> BackgroundTask:
        """Create and register a new background task."""
        task_id = uuid.uuid4().hex[:12]
        task = BackgroundTask(task_id=task_id, command=command)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def remove(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def list_active(self) -> list[BackgroundTask]:
        return [t for t in self._tasks.values() if not t.is_complete]

    async def wait_for(self, task_id: str, timeout: float) -> BackgroundTask | None:
        """Wait for a background task to complete.

        Returns the task if completed within timeout, or the task in its
        current state if timeout expires. Returns None if task_id not found.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.is_complete:
            return task

        try:
            await asyncio.wait_for(task._completion_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass  # Return task in current state

        return task

    async def spawn_background(
        self,
        task: BackgroundTask,
        exec_args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Spawn a background command via asyncio.create_task.

        This is non-blocking -- it schedules the subprocess and returns
        immediately. The asyncio task is tracked on the BackgroundTask
        so it can be cancelled during shutdown.
        """
        loop = asyncio.get_running_loop()
        asyncio_task = loop.create_task(
            self._run_background(task, exec_args, cwd, env)
        )
        task._asyncio_task = asyncio_task

    async def _run_background(
        self,
        task: BackgroundTask,
        exec_args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Run a command in the background, streaming output into task buffers.

        Uses pure asyncio subprocess APIs (not anyio) so that coroutines
        dispatched via asyncio.create_task execute correctly without needing
        an anyio task context.
        """
        # Use start_new_session on POSIX so we can kill the process group
        kwargs: dict = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        try:
            process = await asyncio.create_subprocess_exec(
                *exec_args,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )
            task._process = process

            async def _drain_stdout() -> None:
                assert process.stdout is not None
                while True:
                    chunk = await process.stdout.read(8192)
                    if not chunk:
                        break
                    task.stdout_buffer.extend(chunk)

            async def _drain_stderr() -> None:
                assert process.stderr is not None
                while True:
                    chunk = await process.stderr.read(8192)
                    if not chunk:
                        break
                    task.stderr_buffer.extend(chunk)

            # Drain both pipes concurrently, then wait for exit
            await asyncio.gather(_drain_stdout(), _drain_stderr())
            await process.wait()
            task.exit_code = process.returncode
        except asyncio.CancelledError:
            # Server shutdown -- kill the process
            if task._process is not None and task._process.returncode is None:
                _kill_process_tree(task._process.pid)
                try:
                    task._process.kill()
                except (OSError, ProcessLookupError):
                    pass
            if task.exit_code is None:
                task.exit_code = -1
            raise
        except Exception:
            if task.exit_code is None:
                task.exit_code = -1
        finally:
            task._process = None
            task._asyncio_task = None
            task.completed_at = time.monotonic()
            task._completion_event.set()

    async def _reap_loop(self) -> None:
        """Periodically remove completed tasks older than the TTL."""
        try:
            while True:
                await asyncio.sleep(60.0)  # Check every minute
                now = time.monotonic()
                to_remove = [
                    tid
                    for tid, t in self._tasks.items()
                    if t.is_complete
                    and t.completed_at is not None
                    and (now - t.completed_at) > _COMPLETED_TASK_TTL
                ]
                for tid in to_remove:
                    self._tasks.pop(tid, None)
        except asyncio.CancelledError:
            pass

    # Keep old method name for backward compatibility with tests
    async def run_background(
        self,
        task: BackgroundTask,
        exec_args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Run a command in the background (legacy entry point).

        Prefer spawn_background() for non-blocking dispatch.
        """
        await self._run_background(task, exec_args, cwd, env)


def _kill_process_tree(pid: int) -> None:
    """Terminate a process and its children by PID."""
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
