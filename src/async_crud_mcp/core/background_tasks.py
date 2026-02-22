"""Background task registry for long-running shell commands.

Uses asyncio subprocesses for reliable background execution with streaming
output and no pipe deadlocks.

Tracks asyncio tasks for proper cancellation on shutdown. Completed
tasks are reaped after a configurable TTL to prevent unbounded memory growth.

PID persistence: Active process PIDs are written to a tasks.json file so
that orphaned processes can be detected and killed on server restart.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


# How long completed tasks stay in registry before reaping (seconds)
_COMPLETED_TASK_TTL = 300.0  # 5 minutes

# How long a running task is allowed before being killed as stale (seconds)
_RUNNING_TASK_TTL = 600.0  # 10 minutes


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
    _pid: int | None = field(default=None, repr=False)

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


class _TaskPidTracker:
    """Persists active task PIDs to disk for orphan detection across restarts.

    Writes a JSON file containing PIDs and metadata for all running tasks.
    On startup, reads this file to find processes that survived a crash.
    """

    def __init__(self, pid_file: Path) -> None:
        self._pid_file = pid_file
        self._entries: dict[str, dict[str, Any]] = {}

    def record(self, task_id: str, pid: int, command: str, image: str = "") -> None:
        """Record a new active task PID."""
        self._entries[task_id] = {
            "pid": pid,
            "command": command[:200],
            "started_at": time.time(),
            "image": image,
        }
        self._flush()

    def remove(self, task_id: str) -> None:
        """Remove a completed task PID."""
        if task_id in self._entries:
            del self._entries[task_id]
            self._flush()

    def load_orphans(self) -> list[dict[str, Any]]:
        """Load PIDs from a previous server session.

        Returns list of entries with pid, command, started_at.
        Clears the file after reading.
        """
        if not self._pid_file.exists():
            return []
        try:
            with open(self._pid_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = list(data.get("tasks", {}).values())
            # Clear file immediately - we'll rebuild as new tasks spawn
            self._flush()
            return entries
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read task PID file: {e}")
            return []

    def _flush(self) -> None:
        """Write current entries to disk."""
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "updated_at": time.time(),
                "tasks": self._entries,
            }
            tmp = self._pid_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            tmp.replace(self._pid_file)
        except OSError as e:
            logger.warning(f"Could not write task PID file: {e}")


class BackgroundTaskRegistry:
    """Manages background shell tasks with output capture.

    Uses asyncio.create_task for launching background work (required for
    non-blocking dispatch in request-response servers), while tracking
    tasks for proper cleanup on shutdown.

    Features:
    - Completed task reaping after TTL
    - Stale running task detection and kill after running TTL
    - PID persistence across restarts for orphan cleanup
    - Process tree killing on Windows (taskkill /T /F)
    """

    def __init__(
        self,
        pid_file: Path | None = None,
        running_task_ttl: float = _RUNNING_TASK_TTL,
    ) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._reaper_task: asyncio.Task | None = None
        self._running_task_ttl = running_task_ttl

        # PID tracker for orphan detection
        if pid_file is not None:
            self._pid_tracker: _TaskPidTracker | None = _TaskPidTracker(pid_file)
        else:
            try:
                from ..daemon.paths import get_data_dir
                self._pid_tracker = _TaskPidTracker(get_data_dir() / "tasks.json")
            except Exception:
                # Running outside daemon context (e.g. unit tests) -- disable tracking
                self._pid_tracker = None

    async def start(self) -> None:
        """Start the reaper loop and clean up orphans. Call once during server startup."""
        self._cleanup_orphans()
        if self._reaper_task is None:
            self._reaper_task = asyncio.create_task(self._reap_loop())

    def _cleanup_orphans(self) -> None:
        """Detect and kill orphaned processes from a previous server session.

        Reads persisted PIDs, checks if they're still running, and kills
        any that are still alive. This handles the case where the server
        crashed and left processes running.
        """
        if self._pid_tracker is None:
            return
        orphans = self._pid_tracker.load_orphans()
        if not orphans:
            return

        logger.info(f"Checking {len(orphans)} potentially orphaned processes")
        killed = 0
        skipped = 0
        for entry in orphans:
            pid = entry.get("pid")
            command = entry.get("command", "<unknown>")
            started_at = entry.get("started_at", 0)
            expected_image = entry.get("image", "")
            if pid is None:
                continue

            if not _is_process_alive(pid):
                logger.debug(f"Orphan PID={pid} already exited")
                continue

            # Guard against PID reuse: verify the process image matches
            # what we originally spawned (e.g. "bash", "bash.exe").
            # If the PID was reused by an unrelated process, skip it.
            if expected_image:
                actual_image = _get_process_image(pid)
                if actual_image is not None:
                    # Compare base names case-insensitively (bash vs bash.exe)
                    expected_base = Path(expected_image).stem.lower()
                    actual_base = Path(actual_image).stem.lower()
                    if expected_base != actual_base:
                        logger.info(
                            f"Skipping PID={pid}: image mismatch "
                            f"(expected={expected_image}, actual={actual_image}) "
                            f"-- likely PID reuse by unrelated process"
                        )
                        skipped += 1
                        continue

            age_s = time.time() - started_at if started_at else 0
            logger.warning(
                f"Killing orphaned process PID={pid} "
                f"(age={age_s:.0f}s, cmd={command[:60]})"
            )
            _kill_process_tree(pid)
            killed += 1

        if killed > 0 or skipped > 0:
            logger.info(
                f"Orphan cleanup: {killed} killed, {skipped} skipped (PID reuse)"
            )

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
                # Remove from PID tracker
                if self._pid_tracker is not None:
                    self._pid_tracker.remove(task.task_id)

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
        if self._pid_tracker is not None:
            self._pid_tracker.remove(task_id)

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
            task._pid = process.pid

            # Persist PID for orphan detection across restarts
            if self._pid_tracker is not None:
                # Store the shell image name so orphan cleanup can verify
                # the PID still belongs to a shell process, not a reused PID
                image = Path(exec_args[0]).name if exec_args else ""
                self._pid_tracker.record(
                    task.task_id, process.pid, task.command, image=image,
                )

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
            # Server shutdown or stale task kill -- kill the process
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
            # Remove from PID tracker now that process is done
            if self._pid_tracker is not None:
                self._pid_tracker.remove(task.task_id)

    async def _reap_loop(self) -> None:
        """Periodically reap completed tasks and kill stale running tasks."""
        try:
            while True:
                await asyncio.sleep(60.0)  # Check every minute
                now = time.monotonic()

                # Reap completed tasks older than TTL
                to_remove = [
                    tid
                    for tid, t in self._tasks.items()
                    if t.is_complete
                    and t.completed_at is not None
                    and (now - t.completed_at) > _COMPLETED_TASK_TTL
                ]
                for tid in to_remove:
                    self._tasks.pop(tid, None)

                # Kill stale running tasks that exceed the running TTL
                for task in list(self._tasks.values()):
                    if not task.is_complete:
                        elapsed = now - task.started_at
                        if elapsed > self._running_task_ttl:
                            logger.warning(
                                f"Killing stale task {task.task_id} "
                                f"(running {elapsed:.0f}s > {self._running_task_ttl:.0f}s TTL, "
                                f"cmd={task.command[:60]})"
                            )
                            # Kill the process tree
                            if task._process is not None and task._process.returncode is None:
                                _kill_process_tree(task._process.pid)
                                try:
                                    task._process.kill()
                                except (OSError, ProcessLookupError):
                                    pass
                            # Cancel the asyncio task
                            if task._asyncio_task is not None and not task._asyncio_task.done():
                                task._asyncio_task.cancel()

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


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _get_process_image(pid: int) -> str | None:
    """Get the image/executable name for a running process.

    Returns the process name (e.g. "bash", "bash.exe") or None if the
    process doesn't exist or the name can't be determined.
    Used to verify a PID still belongs to a process we spawned, guarding
    against PID reuse by unrelated processes.
    """
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # CSV format: "Image Name","PID","Session Name","Session#","Mem Usage"
            for line in result.stdout.strip().splitlines():
                if str(pid) in line:
                    parts = line.strip('"').split('","')
                    if parts:
                        return parts[0]
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None
    else:
        # POSIX: read /proc/{pid}/comm (Linux) or /proc/{pid}/cmdline
        try:
            comm_path = Path(f"/proc/{pid}/comm")
            if comm_path.exists():
                return comm_path.read_text().strip()
            # Fallback: cmdline (first arg)
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.exists():
                cmdline = cmdline_path.read_bytes().split(b"\x00")
                if cmdline and cmdline[0]:
                    return Path(cmdline[0].decode("utf-8", errors="replace")).name
        except (OSError, PermissionError):
            pass
        return None


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
            pass
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
            pass
