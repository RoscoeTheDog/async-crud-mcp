"""Background task registry for long-running shell commands.

Uses asyncio subprocesses for reliable background execution with streaming
output and no pipe deadlocks. Process containment via Job Objects (Windows)
or RLIMIT_NPROC (POSIX) prevents fork bombs and runaway process creation.

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

from async_crud_mcp.core import process_guard


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
    _job: Any = field(default=None, repr=False)

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

    def record(self, task_id: str, pid: int, command: str, created_at: float | None = None) -> None:
        """Record a new active task PID with its creation time."""
        entry: dict[str, Any] = {
            "pid": pid,
            "command": command[:200],
            "started_at": time.time(),
        }
        if created_at is not None:
            entry["created_at"] = created_at
        self._entries[task_id] = entry
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
        process_limit: int = 50,
    ) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._reaper_task: asyncio.Task | None = None
        self._running_task_ttl = running_task_ttl
        self._process_limit = process_limit

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
            expected_created_at = entry.get("created_at")
            if pid is None:
                continue

            if not _is_process_alive(pid):
                logger.debug(f"Orphan PID={pid} already exited")
                continue

            # Guard against PID reuse: verify the process creation time matches
            # what we recorded when we spawned it. Even if the OS reuses a PID
            # for another process with the same image name, its creation time
            # will differ from ours.
            if expected_created_at is not None:
                actual_created_at = _get_process_creation_time(pid)
                if actual_created_at is not None:
                    if abs(actual_created_at - expected_created_at) > 2.0:
                        logger.info(
                            f"Skipping PID={pid}: creation time mismatch "
                            f"(expected={expected_created_at:.3f}, "
                            f"actual={actual_created_at:.3f}) "
                            f"-- PID reuse detected"
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

        Called during server shutdown to prevent orphaned subprocesses. The
        cancelled asyncio tasks are awaited so their subprocess transports/pipes
        are actually closed before this returns: otherwise the Windows
        ProactorEventLoop hangs in GetQueuedCompletionStatus during loop teardown
        on an orphaned subprocess read. Killing the process first EOFs the pipe,
        which lets the awaited cancellation unwind cleanly (no IOCP hang).
        """
        pending: list[asyncio.Task] = []

        # Stop the reaper
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            pending.append(self._reaper_task)
            self._reaper_task = None

        # Kill all active processes and cancel their asyncio tasks
        for task in list(self._tasks.values()):
            if not task.is_complete:
                # Kill via Job Object first (Windows), then fallback to tree kill
                if task._job is not None:
                    process_guard.terminate_job(task._job)
                    process_guard.close_job(task._job)
                    task._job = None
                elif task._process is not None and task._process.returncode is None:
                    _kill_process_tree(task._process.pid)
                if task._process is not None and task._process.returncode is None:
                    try:
                        task._process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                # Cancel the asyncio task
                if task._asyncio_task is not None and not task._asyncio_task.done():
                    task._asyncio_task.cancel()
                    pending.append(task._asyncio_task)
                # Remove from PID tracker
                if self._pid_tracker is not None:
                    self._pid_tracker.remove(task.task_id)

        # Await the cancelled tasks so their subprocess transports close in-loop
        # (prevents the Windows ProactorEventLoop IOCP teardown hang).
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

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

    async def wait_for_any(self, task_ids: list[str], timeout: float) -> list[BackgroundTask]:
        """Wait for any of the given tasks to complete.

        Returns immediately with all already-completed tasks.
        If none are complete, blocks until the first one completes or timeout.
        Returns empty list if timeout expires with none completed.
        """
        tasks = [t for tid in task_ids if (t := self._tasks.get(tid)) is not None]
        if not tasks:
            return []

        completed = [t for t in tasks if t.is_complete]
        if completed:
            return completed

        # Race: wait for first completion event among running tasks
        futs = [asyncio.ensure_future(t._completion_event.wait()) for t in tasks]
        try:
            done, pending = await asyncio.wait(
                futs, timeout=timeout, return_when=asyncio.FIRST_COMPLETED,
            )
            for fut in pending:
                fut.cancel()
        except asyncio.TimeoutError:
            for fut in futs:
                fut.cancel()
            return []

        return [t for t in tasks if t.is_complete]

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
        an anyio task context. Wraps the process in a Job Object (Windows)
        or RLIMIT_NPROC (POSIX) for fork bomb containment.
        """
        kwargs: dict = {}
        job = None

        if sys.platform == "win32":
            job = process_guard.create_job(self._process_limit)
            kwargs["creationflags"] = (
                process_guard.CREATE_SUSPENDED | process_guard.CREATE_NO_WINDOW
            )
        else:
            kwargs["preexec_fn"] = process_guard.make_preexec_fn(self._process_limit)
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
            task._job = job

            if job is not None:
                process_guard.assign_to_job(job, process.pid)
                process_guard.resume_process(process.pid)

            # Persist PID for orphan detection across restarts
            if self._pid_tracker is not None:
                created_at = _get_process_creation_time(process.pid)
                self._pid_tracker.record(
                    task.task_id, process.pid, task.command, created_at=created_at,
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
            if task._job is not None:
                process_guard.terminate_job(task._job)
            elif task._process is not None and task._process.returncode is None:
                _kill_process_tree(task._process.pid)
            if task._process is not None and task._process.returncode is None:
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
            if task._job is not None:
                process_guard.close_job(task._job)
                task._job = None
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
                            # Kill via Job Object first, then fallback
                            if task._job is not None:
                                process_guard.terminate_job(task._job)
                                process_guard.close_job(task._job)
                                task._job = None
                            elif task._process is not None and task._process.returncode is None:
                                _kill_process_tree(task._process.pid)
                            if task._process is not None and task._process.returncode is None:
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
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except (OSError, AttributeError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _get_process_creation_time(pid: int) -> float | None:
    """Get the creation time (Unix epoch seconds) for a running process.

    Returns the process creation time as a float, or None if the process
    doesn't exist or the time can't be determined.
    Used to definitively verify a PID still belongs to the process we spawned,
    guarding against PID reuse -- even by processes with the same image name.
    """
    if sys.platform == "win32":
        return _get_creation_time_windows(pid)
    elif sys.platform == "linux":
        return _get_creation_time_linux(pid)
    else:
        # macOS and other POSIX
        return _get_creation_time_posix_fallback(pid)


def _get_creation_time_windows(pid: int) -> float | None:
    """Get process creation time on Windows via kernel32 ctypes calls."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            creation_time = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            )
            if not ok:
                return None
            # FILETIME = 100-nanosecond intervals since 1601-01-01 UTC
            # Convert to Unix epoch seconds (difference = 11644473600 seconds)
            ft = (creation_time.dwHighDateTime << 32) | creation_time.dwLowDateTime
            EPOCH_DIFF_SECS = 11644473600
            return (ft / 10_000_000) - EPOCH_DIFF_SECS
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return None


def _get_creation_time_linux(pid: int) -> float | None:
    """Get process creation time on Linux via /proc/{pid}/stat."""
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return None
        stat_content = stat_path.read_text()
        # Field 22 = starttime (clock ticks since boot).
        # The comm field (field 2) is in parens and can contain spaces/parens,
        # so find the last ')' to skip past it reliably.
        after_comm = stat_content[stat_content.rfind(")") + 2 :]
        fields = after_comm.split()
        # After comm, fields are indexed from 0: state(0)=field3 ... starttime(19)=field22
        starttime_ticks = int(fields[19])

        clock_ticks_per_sec = os.sysconf("SC_CLK_TCK")

        # Get boot time from /proc/stat
        boot_time = None
        proc_stat = Path("/proc/stat").read_text()
        for line in proc_stat.splitlines():
            if line.startswith("btime "):
                boot_time = int(line.split()[1])
                break
        if boot_time is None:
            return None

        return boot_time + (starttime_ticks / clock_ticks_per_sec)
    except (OSError, PermissionError, IndexError, ValueError):
        return None


def _get_creation_time_posix_fallback(pid: int) -> float | None:
    """Get process creation time on macOS/other POSIX via ps subprocess."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lstart = result.stdout.strip()
        if not lstart:
            return None
        from datetime import datetime
        # ps lstart format: "Mon Jan  1 12:00:00 2024"
        dt = datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y")
        return dt.timestamp()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


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
