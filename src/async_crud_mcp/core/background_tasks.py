"""Background task registry for long-running shell commands.

Uses anyio for reliable subprocess management with streaming output
and no pipe deadlocks.
"""

import subprocess
import time
import uuid
from dataclasses import dataclass, field

import anyio


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
    _completion_event: anyio.Event = field(default_factory=anyio.Event)

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
    """Manages background shell tasks with output capture."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}

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

        with anyio.move_on_after(timeout):
            await task._completion_event.wait()

        return task

    async def run_background(
        self,
        task: BackgroundTask,
        exec_args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Run a command in the background, streaming output into task buffers.

        This should be called inside a task group (e.g. via anyio.create_task_group).
        """
        try:
            async with await anyio.open_process(
                exec_args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as process:
                async with anyio.create_task_group() as tg:

                    async def _drain_stdout() -> None:
                        if process.stdout:
                            async for chunk in process.stdout:
                                task.stdout_buffer.extend(chunk)

                    async def _drain_stderr() -> None:
                        if process.stderr:
                            async for chunk in process.stderr:
                                task.stderr_buffer.extend(chunk)

                    tg.start_soon(_drain_stdout)
                    tg.start_soon(_drain_stderr)

                # Wait for process to finish after pipes are drained
                await process.wait()
                task.exit_code = process.returncode
        except Exception:
            if task.exit_code is None:
                task.exit_code = -1
        finally:
            task.completed_at = time.monotonic()
            task._completion_event.set()
