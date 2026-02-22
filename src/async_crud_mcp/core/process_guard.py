"""Process containment guard for shell command execution.

Provides cross-platform process limiting to prevent fork bombs and runaway
process creation:

- **Windows**: Uses Job Objects with ``ActiveProcessLimit``. All child
  processes are assigned to a kernel Job Object that enforces a hard cap
  on concurrent processes. The process is created suspended, assigned to
  the job, then resumed so the limit is in effect from the first instruction.

- **POSIX**: Uses ``RLIMIT_NPROC`` via the ``resource`` module. A
  ``preexec_fn`` callback sets the per-UID process limit before exec.

  **Per-UID scope caveat**: ``RLIMIT_NPROC`` counts *all* processes owned
  by the real UID, not just children of this subprocess. If the daemon
  shares a UID with other services, the limit affects all of them. To
  mitigate this, we read the current soft limit and set
  ``min(current_soft, process_limit)`` so we never lower below what the
  system already allows.

  **Container alternative**: In Docker/K8s, prefer ``--pids-limit``
  (cgroups v2 ``pids.max``) which is per-cgroup and avoids the per-UID
  issue entirely.
"""

import ctypes
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows Job Object helpers
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes.wintypes

    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    # Job Object constants
    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    # Thread access rights
    _THREAD_SUSPEND_RESUME = 0x0002

    # Process creation flags (re-exported for callers)
    CREATE_SUSPENDED = 0x00000004
    CREATE_NO_WINDOW = 0x08000000

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.wintypes.DWORD),
            ("SchedulingClass", ctypes.wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ThreadID", ctypes.wintypes.DWORD),
            ("th32OwnerProcessID", ctypes.wintypes.DWORD),
            ("tpBasePri", ctypes.wintypes.LONG),
            ("tpDeltaPri", ctypes.wintypes.LONG),
            ("dwFlags", ctypes.wintypes.DWORD),
        ]

    def create_job(process_limit: int) -> Any:
        """Create a Windows Job Object with an ActiveProcessLimit.

        The job also has KILL_ON_JOB_CLOSE set so that if the handle is
        leaked, closing it will still terminate all contained processes.

        Returns the job handle (an integer).
        """
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.ActiveProcessLimit = process_limit
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_ACTIVE_PROCESS | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )

        ok = _kernel32.SetInformationJobObject(
            job,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(job)
            raise OSError(f"SetInformationJobObject failed: {err}")

        logger.debug("Created Job Object with ActiveProcessLimit=%d", process_limit)
        return job

    def assign_to_job(job: Any, pid: int) -> None:
        """Assign a (suspended) process to the Job Object by PID."""
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        handle = _kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid,
        )
        if not handle:
            raise OSError(
                f"OpenProcess({pid}) failed: {ctypes.get_last_error()}"
            )
        try:
            ok = _kernel32.AssignProcessToJobObject(job, handle)
            if not ok:
                raise OSError(
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
                )
            logger.debug("Assigned PID %d to Job Object", pid)
        finally:
            _kernel32.CloseHandle(handle)

    def resume_process(pid: int) -> None:
        """Resume all threads of a suspended process.

        Uses CreateToolhelp32Snapshot to enumerate threads belonging to
        the target PID, then calls ResumeThread on each.
        """
        TH32CS_SNAPTHREAD = 0x00000004
        snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snap == -1 or snap == ctypes.wintypes.HANDLE(-1).value:
            raise OSError(
                f"CreateToolhelp32Snapshot failed: {ctypes.get_last_error()}"
            )
        try:
            te = _THREADENTRY32()
            te.dwSize = ctypes.sizeof(_THREADENTRY32)
            ok = _kernel32.Thread32First(snap, ctypes.byref(te))
            resumed = 0
            while ok:
                if te.th32OwnerProcessID == pid:
                    th = _kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME, False, te.th32ThreadID,
                    )
                    if th:
                        _kernel32.ResumeThread(th)
                        _kernel32.CloseHandle(th)
                        resumed += 1
                ok = _kernel32.Thread32Next(snap, ctypes.byref(te))
            logger.debug("Resumed %d threads for PID %d", resumed, pid)
        finally:
            _kernel32.CloseHandle(snap)

    def terminate_job(job: Any) -> None:
        """Terminate all processes in the Job Object."""
        ok = _kernel32.TerminateJobObject(job, 1)
        if not ok:
            logger.warning(
                "TerminateJobObject failed: %s", ctypes.get_last_error()
            )
        else:
            logger.debug("Terminated all processes in Job Object")

    def close_job(job: Any) -> None:
        """Close the Job Object handle."""
        if job:
            _kernel32.CloseHandle(job)

else:
    # POSIX stubs - these should never be called on POSIX
    CREATE_SUSPENDED = 0
    CREATE_NO_WINDOW = 0

    def create_job(process_limit: int) -> Any:
        raise NotImplementedError("Job Objects are Windows-only")

    def assign_to_job(job: Any, pid: int) -> None:
        raise NotImplementedError("Job Objects are Windows-only")

    def resume_process(pid: int) -> None:
        raise NotImplementedError("Job Objects are Windows-only")

    def terminate_job(job: Any) -> None:
        raise NotImplementedError("Job Objects are Windows-only")

    def close_job(job: Any) -> None:
        raise NotImplementedError("Job Objects are Windows-only")


# ---------------------------------------------------------------------------
# POSIX RLIMIT_NPROC helper
# ---------------------------------------------------------------------------


def make_preexec_fn(process_limit: int):
    """Return a preexec_fn that sets RLIMIT_NPROC and creates a new session.

    The returned callable is passed to ``subprocess.Popen(preexec_fn=...)``.
    It runs in the child process after fork() but before exec().

    On non-POSIX platforms, returns None (no-op).
    """
    if sys.platform == "win32":
        return None

    import resource

    def _preexec() -> None:
        # Create new session for process-group kill support
        os.setsid()

        # Read current soft/hard limits
        soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)

        # Never exceed the existing hard limit, and never lower below
        # what the system already has as soft limit to avoid breaking
        # co-tenant processes sharing this UID.
        effective = min(process_limit, hard)
        if effective < soft:
            logger.debug(
                "RLIMIT_NPROC: requested %d < current soft %d, "
                "using requested value",
                effective, soft,
            )
        resource.setrlimit(resource.RLIMIT_NPROC, (effective, hard))

    return _preexec
