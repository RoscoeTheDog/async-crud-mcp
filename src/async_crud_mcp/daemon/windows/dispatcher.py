"""Multi-User Dispatcher for Windows service context.

Manages per-user MCP server worker processes from a single system-wide
Windows service running as LocalSystem. Responds to session logon/logoff
events to create and destroy workers on demand.

Architecture:
    Windows Service (LocalSystem) - single system-wide service
        |-- Worker: Alice (PID 123, RunAsUser)
        |-- Worker: Bob   (PID 456, RunAsUser)
        '-- Worker: Carol (PID 789, RunAsUser)

    macOS/Linux use native per-user service mechanisms (launchd/systemd),
    so this dispatcher is Windows-only.

Key design decisions:
    - Username is the primary worker key (not session_id)
    - Tracks session_ids: set[int] for multi-session same user (console + RDP)
    - Only stops worker when the last session for that user ends
    - Skips system accounts (SYSTEM, LOCAL SERVICE, NETWORK SERVICE)
    - Per-user logs under ProgramData/async-crud-mcp/logs/{username}/

Bug fixes from reference implementation:
    - BUG-04: Uses subprocess.DEVNULL instead of PIPE to prevent buffer deadlock
    - BUG-05/06: Logging fallback chain (ProgramData -> LocalAppData -> Temp) (GAP-8)
    - BUG-13: Stale process cleanup on worker restart
    - GAP-2: Single async-crud-mcp convention
    - ADR-012: Port conflict detection, orphan process cleanup, TCP health polling

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name
    async_crud_mcp  - Python package name

Usage:
    Called from bootstrap_service.py SvcDoRun() in Windows service context.

    from .dispatcher import MultiUserDispatcher
    dispatcher = MultiUserDispatcher()
    await dispatcher.run()
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional

# Platform check
if sys.platform != 'win32':
    raise ImportError(
        "dispatcher module is only available on Windows. "
        f"Current platform: {sys.platform}"
    )

# pywin32 availability check
try:
    import win32api
    import win32con
    import win32process
    import win32profile
    import win32ts
except ImportError as e:
    raise ImportError(
        "pywin32 is required for the multi-user dispatcher. "
        "Install with: pip install pywin32"
    ) from e

from loguru import logger

from ..paths import (
    APP_NAME,
    _get_user_profile_path,
    get_user_config_file_path,
    get_user_logs_dir,
)
from ..config_init import DEFAULT_PORT

# Service/system accounts to skip (uppercase for case-insensitive comparison)
SYSTEM_ACCOUNTS = frozenset({
    '', 'SYSTEM', 'LOCAL SERVICE', 'NETWORK SERVICE',
    'DWM-1', 'DWM-2', 'DWM-3', 'UMFD-0', 'UMFD-1', 'UMFD-2', 'UMFD-3',
})

# Default poll interval for worker health checks (seconds)
DEFAULT_POLL_INTERVAL = 5

# Grace period after worker start before checking port connectivity (seconds)
STARTUP_GRACE_SECONDS = 15


@dataclass
class UserWorker:
    """Tracks a single user's MCP server worker process.

    Attributes:
        username: Windows username for this worker
        session_ids: Set of WTS session IDs for this user (supports multi-session)
        user_token: Windows user token handle from WTSQueryUserToken
        config_path: Path to the user's config.json
        config_mtime: Last known modification time of config file
        profile_path: Path to user's profile directory
        process_handle: Win32 process handle from CreateProcessAsUser
        process_id: PID of the worker process
        stderr_file: Open file handle for worker stderr log
        started_at: Timestamp when worker process was started
    """
    username: str
    session_ids: set[int] = field(default_factory=set)
    user_token: Optional[int] = None
    config_path: Optional[Path] = None
    config_mtime: Optional[float] = None
    profile_path: Optional[Path] = None
    process_handle: Optional[int] = None
    process_id: Optional[int] = None
    stderr_file: Optional[IO[str]] = None
    started_at: Optional[float] = None


class MultiUserDispatcher:
    """Session-aware dispatcher that manages per-user MCP server workers.

    This class is the top-level orchestrator for the Windows service context.
    It replaces BootstrapDaemon when running as a system-wide service.

    The dispatcher:
    - Enumerates existing sessions on startup
    - Responds to session logon/logoff events
    - Starts one MCP server worker per user via CreateProcessAsUser
    - Polls worker health and restarts crashed processes
    - Reloads config on file change and restarts workers if needed
    - Stops all workers on shutdown
    """

    def __init__(self) -> None:
        self.running = True
        self.workers: dict[str, UserWorker] = {}
        self._configure_logging()

    def _configure_logging(self) -> None:
        """Configure dispatcher-level logging with fallback chain (GAP-8).

        Tries ProgramData first, falls back to LocalAppData, then Temp.
        This ensures logging works even when the service runs as LocalSystem
        with limited access to user directories (BUG-05, BUG-06).
        """
        log_file = None

        # Try ProgramData first (system-wide location, preferred for services)
        programdata = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
        log_dir = Path(programdata) / APP_NAME / 'logs'

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / 'dispatcher.log'
            # Test if we can write to the file
            with open(log_file, 'a', encoding='utf-8') as f:
                pass
        except PermissionError:
            # Fall back to LocalAppData
            localappdata = os.environ.get('LOCALAPPDATA', '')
            if localappdata:
                log_dir = Path(localappdata) / APP_NAME / 'logs'
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_file = log_dir / 'dispatcher.log'
                except Exception:
                    log_file = None

            if log_file is None:
                # Last resort: temp directory
                import tempfile
                log_dir = Path(tempfile.gettempdir()) / APP_NAME / 'logs'
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / 'dispatcher.log'

        logger.remove()
        logger.add(
            log_file,
            rotation="10 MB",
            retention=3,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
            level="DEBUG",
            enqueue=True,
        )

        self.log_file = log_file
        logger.info(f"Dispatcher logging configured: {log_file}")

    async def run(self) -> None:
        """Main dispatcher loop.

        On startup, enumerates existing sessions to catch users already
        logged in. Then polls worker health periodically until shutdown.
        """
        logger.info("Multi-user dispatcher starting")

        try:
            self._enumerate_existing_sessions()

            while self.running:
                try:
                    self._poll_workers()
                    await asyncio.sleep(DEFAULT_POLL_INTERVAL)
                except Exception as e:
                    logger.error(f"Error in dispatcher main loop: {e}")
                    await asyncio.sleep(DEFAULT_POLL_INTERVAL)

        finally:
            logger.info("Multi-user dispatcher shutting down")
            self._stop_all_workers()
            await logger.complete()

    def on_session_logon(self, session_id: int) -> None:
        """Handle a WTS session logon event.

        If the user already has a running worker (from another session),
        just track the additional session ID. Otherwise, create and start
        a new worker.

        Args:
            session_id: WTS session ID from the logon event
        """
        username = _get_username_for_session(session_id)
        if not username or username.upper() in SYSTEM_ACCOUNTS:
            logger.debug(f"Ignoring logon for session {session_id} (system account or empty)")
            return

        if username in self.workers:
            self.workers[username].session_ids.add(session_id)
            logger.info(f"Added session {session_id} to existing worker for {username}")
            return

        logger.info(f"Session logon: {username} (session {session_id})")
        try:
            worker = self._create_worker(username, session_id)
            self.workers[username] = worker
            self._start_worker(worker)
        except Exception as e:
            logger.error(f"Failed to create worker for {username}: {e}")

    def on_session_logoff(self, session_id: int) -> None:
        """Handle a WTS session logoff event.

        Removes the session ID from the user's worker. If this was the
        last session for that user, stops and removes the worker.

        Args:
            session_id: WTS session ID from the logoff event
        """
        username = _get_username_for_session(session_id)
        if not username:
            # Session already gone, try to find worker by session_id
            for uname, worker in list(self.workers.items()):
                if session_id in worker.session_ids:
                    worker.session_ids.discard(session_id)
                    if not worker.session_ids:
                        logger.info(f"Last session gone for {uname}, stopping worker")
                        self._stop_worker(worker)
                        del self.workers[uname]
                    return
            return

        worker = self.workers.get(username)
        if worker:
            worker.session_ids.discard(session_id)
            logger.info(
                f"Session {session_id} logoff for {username}, "
                f"{len(worker.session_ids)} sessions remaining"
            )
            if not worker.session_ids:
                logger.info(f"Last session for {username}, stopping worker")
                self._stop_worker(worker)
                del self.workers[username]

    def _enumerate_existing_sessions(self) -> None:
        """On service start, find all logged-in users via WTSEnumerateSessions.

        This catches users who were already logged in when the service started.
        """
        try:
            sessions = win32ts.WTSEnumerateSessions(
                win32ts.WTS_CURRENT_SERVER_HANDLE
            )
        except Exception as e:
            logger.error(f"Failed to enumerate sessions: {e}")
            return

        for session in sessions:
            sid = int(session['SessionId'])
            state = session.get('State', None)

            # Only consider active sessions (WTSActive = 0)
            if state != 0:
                continue

            try:
                username = win32ts.WTSQuerySessionInformation(
                    win32ts.WTS_CURRENT_SERVER_HANDLE,
                    sid,
                    win32ts.WTSUserName
                )
            except Exception:
                continue

            if username and username.upper() not in SYSTEM_ACCOUNTS:
                logger.info(f"Found existing session: {username} (session {sid})")
                self.on_session_logon(sid)

    def _create_worker(self, username: str, session_id: int) -> UserWorker:
        """Create a UserWorker with resolved paths and user token.

        Args:
            username: Windows username
            session_id: WTS session ID to get the user token from

        Returns:
            Configured UserWorker instance
        """
        profile_path = _get_user_profile_path(username)
        config_path = get_user_config_file_path(username)

        # Get user token for CreateProcessAsUser
        user_token = win32ts.WTSQueryUserToken(session_id)

        worker = UserWorker(
            username=username,
            session_ids={session_id},
            user_token=user_token,
            config_path=config_path,
            profile_path=profile_path,
        )

        logger.info(f"Created worker for {username}: config={config_path}, profile={profile_path}")
        return worker

    def _start_worker(self, worker: UserWorker) -> None:
        """Start MCP server as the user via CreateProcessAsUser.

        Reads the user's config to check if the daemon is enabled,
        then launches the MCP server process running as the user.
        Performs a port availability pre-check and kills orphan processes
        if the port is occupied (ADR-012).

        Args:
            worker: UserWorker to start
        """
        # Load user settings
        settings = _load_user_settings(worker.config_path)
        if not settings.get('daemon', {}).get('enabled', True):
            logger.info(f"Daemon disabled for {worker.username}, skipping")
            return

        # Read host/port from config (fall back to defaults)
        host = settings.get('daemon', {}).get('host', '127.0.0.1')
        port = settings.get('daemon', {}).get('port', DEFAULT_PORT)

        # Pre-check: ensure the port is available before spawning worker (ADR-012)
        available, owning_pid = self._check_port_available(host, port)
        if not available:
            logger.warning(
                f"Port {port} is occupied by PID {owning_pid} before starting "
                f"worker for {worker.username}"
            )
            # Kill the orphan (but not our own worker if somehow still tracked)
            self._kill_port_owner(port, exclude_pid=worker.process_id)
            # Re-check after kill
            available, _ = self._check_port_available(host, port)
            if not available:
                logger.error(
                    f"Port {port} still occupied after kill attempt, "
                    f"cannot start worker for {worker.username}"
                )
                return

        # Record config mtime for hot-reload detection
        if worker.config_path and worker.config_path.exists():
            worker.config_mtime = worker.config_path.stat().st_mtime

        # Find Python executable (BUG-03: resolve pythonservice.exe -> python.exe)
        python_exe = self._get_python_executable()
        cmd = f'"{python_exe}" -m async_crud_mcp.server'

        # Set up per-user log directory
        user_log_dir = get_user_logs_dir(worker.username)
        user_log_dir.mkdir(parents=True, exist_ok=True)

        stderr_log = user_log_dir / 'mcp_server_stderr.log'

        try:
            # Create environment block for user
            env = win32profile.CreateEnvironmentBlock(worker.user_token, False)

            # Prepare startup info
            startup_info = win32process.STARTUPINFO()
            startup_info.dwFlags = win32con.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = win32con.SW_HIDE

            # Open stderr log file for the worker
            worker.stderr_file = open(stderr_log, 'w', encoding='utf-8')

            # CreateProcessAsUser for per-user isolation
            # CRITICAL: Add CREATE_NEW_PROCESS_GROUP for clean worker termination (AC-17.4)
            creation_flags = (
                win32process.CREATE_NO_WINDOW |
                win32process.CREATE_UNICODE_ENVIRONMENT |
                win32process.CREATE_NEW_PROCESS_GROUP
            )

            hProcess, hThread, dwPid, _dwTid = win32process.CreateProcessAsUser(
                worker.user_token,      # hToken
                python_exe,             # lpApplicationName
                cmd,                    # lpCommandLine
                None,                   # lpProcessAttributes
                None,                   # lpThreadAttributes
                False,                  # bInheritHandles
                creation_flags,         # dwCreationFlags
                env,                    # lpEnvironment
                str(worker.profile_path),  # lpCurrentDirectory
                startup_info            # lpStartupInfo
            )

            # Close the thread handle (we only need the process handle)
            win32api.CloseHandle(hThread)

            worker.process_handle = hProcess
            worker.process_id = dwPid
            worker.started_at = time.time()

            logger.info(
                f"Started MCP server for {worker.username} "
                f"(PID {dwPid}, stderr -> {stderr_log})"
            )

        except Exception as e:
            logger.error(f"Failed to start worker for {worker.username}: {e}")
            worker.process_handle = None
            worker.process_id = None
            if worker.stderr_file:
                try:
                    worker.stderr_file.close()
                except Exception:
                    pass
                worker.stderr_file = None

    def _stop_worker(self, worker: UserWorker) -> None:
        """Terminate user's MCP server process and close handles.

        Args:
            worker: UserWorker to stop
        """
        if worker.process_handle:
            try:
                logger.info(f"Stopping worker for {worker.username} (PID {worker.process_id})")
                win32process.TerminateProcess(worker.process_handle, 0)
            except Exception as e:
                logger.warning(f"Error terminating process for {worker.username}: {e}")
            finally:
                try:
                    win32api.CloseHandle(worker.process_handle)
                except Exception:
                    pass
                worker.process_handle = None
                worker.process_id = None

        if worker.user_token:
            try:
                win32api.CloseHandle(worker.user_token)
            except Exception:
                pass
            worker.user_token = None

        if worker.stderr_file:
            try:
                worker.stderr_file.close()
            except Exception:
                pass
            worker.stderr_file = None

    def _stop_all_workers(self) -> None:
        """Stop all running workers. Called on service shutdown."""
        logger.info(f"Stopping all workers ({len(self.workers)} active)")
        for username, worker in list(self.workers.items()):
            self._stop_worker(worker)
        self.workers.clear()

    def _poll_workers(self) -> None:
        """Check worker health, reload configs, restart crashed processes.

        This is called periodically from the main loop. It checks each
        worker's process status, port connectivity, and config file for
        changes. Includes stale process cleanup on restart (BUG-13) and
        port-level health monitoring (ADR-012).
        """
        for username, worker in list(self.workers.items()):
            # Check if process is still alive
            if worker.process_handle:
                exit_code = win32process.GetExitCodeProcess(worker.process_handle)
                if exit_code != 259:  # STILL_ACTIVE = 259
                    logger.warning(
                        f"Worker for {username} exited (code {exit_code}), restarting"
                    )
                    # Close the old handle (BUG-13: stale process cleanup)
                    try:
                        win32api.CloseHandle(worker.process_handle)
                    except Exception:
                        pass
                    worker.process_handle = None
                    worker.process_id = None

                    if worker.stderr_file:
                        try:
                            worker.stderr_file.close()
                        except Exception:
                            pass
                        worker.stderr_file = None

                    # Re-acquire user token if needed
                    if not worker.user_token and worker.session_ids:
                        try:
                            sid = next(iter(worker.session_ids))
                            worker.user_token = win32ts.WTSQueryUserToken(sid)
                        except Exception as e:
                            logger.error(
                                f"Cannot re-acquire token for {username}: {e}"
                            )
                            continue

                    self._start_worker(worker)

                else:
                    # Process is alive - verify port is actually listening
                    # Skip check during startup grace period (ADR-012)
                    if (
                        worker.started_at is not None
                        and (time.time() - worker.started_at) > STARTUP_GRACE_SECONDS
                    ):
                        settings = _load_user_settings(worker.config_path)
                        host = settings.get('daemon', {}).get('host', '127.0.0.1')
                        port = settings.get('daemon', {}).get('port', DEFAULT_PORT)

                        if not self._is_port_listening(host, port):
                            logger.warning(
                                f"Worker for {username} (PID {worker.process_id}) "
                                f"is alive but port {port} not listening, restarting"
                            )
                            self._stop_worker(worker)

                            # Re-acquire user token if needed
                            if not worker.user_token and worker.session_ids:
                                try:
                                    sid = next(iter(worker.session_ids))
                                    worker.user_token = win32ts.WTSQueryUserToken(sid)
                                except Exception as e:
                                    logger.error(
                                        f"Cannot re-acquire token for {username}: {e}"
                                    )
                                    continue

                            self._start_worker(worker)

            # Check config changes
            self._check_config_reload(worker)

    def _check_config_reload(self, worker: UserWorker) -> None:
        """Check if a worker's config file changed and restart if so.

        Args:
            worker: UserWorker to check
        """
        if not worker.config_path or not worker.config_path.exists():
            return

        try:
            current_mtime = worker.config_path.stat().st_mtime
        except OSError:
            return

        if worker.config_mtime is None:
            worker.config_mtime = current_mtime
            return

        if current_mtime != worker.config_mtime:
            logger.info(f"Config changed for {worker.username}, restarting worker")
            worker.config_mtime = current_mtime

            # Stop and restart with new config
            if worker.process_handle:
                # Save token before stopping (prevent _stop_worker from closing it)
                token = worker.user_token
                worker.user_token = None
                self._stop_worker(worker)
                worker.user_token = token
                self._start_worker(worker)

    # =========================================================================
    # Port resilience helpers (ADR-012)
    # =========================================================================

    def _check_port_available(self, host: str, port: int) -> tuple[bool, Optional[int]]:
        """Check if port is available for binding.

        Attempts a TCP connect to host:port. If something responds,
        the port is already in use.

        Args:
            host: Host address to check
            port: Port number to check

        Returns:
            Tuple of (available, owning_pid_or_None)
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            result = sock.connect_ex((host, port))
            if result == 0:
                # Port is in use - someone is listening
                pid = self._find_port_owner(port)
                return False, pid
            return True, None
        finally:
            sock.close()

    def _is_port_listening(self, host: str, port: int) -> bool:
        """Quick TCP check to see if a port is accepting connections.

        Args:
            host: Host address to check
            port: Port number to check

        Returns:
            True if something is listening on the port
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            result = sock.connect_ex((host, port))
            return result == 0
        finally:
            sock.close()

    def _find_port_owner(self, port: int) -> Optional[int]:
        """Find the PID of the process owning a TCP port (Windows-only).

        Uses PowerShell Get-NetTCPConnection to find the owning process.
        On macOS/Linux, replace with lsof/ss equivalents.

        Args:
            port: Port number to look up

        Returns:
            PID of the owning process, or None if not found
        """
        try:
            cmd = (
                f'powershell -NoProfile -Command "'
                f"(Get-NetTCPConnection -LocalPort {port} "
                f"-State Listen -ErrorAction SilentlyContinue | "
                f'Select-Object -First 1).OwningProcess"'
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5, shell=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            logger.debug(f"Failed to find port owner for {port}: {e}")
        return None

    def _kill_port_owner(self, port: int, exclude_pid: Optional[int] = None) -> bool:
        """Kill the process owning a TCP port (Windows-only).

        Finds the process listening on the port and terminates it,
        unless it matches exclude_pid (e.g., our own worker).
        On macOS/Linux, replace taskkill with kill command.

        Args:
            port: Port number whose owner should be killed
            exclude_pid: PID to skip (don't kill our own worker)

        Returns:
            True if a process was killed, False otherwise
        """
        pid = self._find_port_owner(port)
        if pid is None:
            logger.debug(f"No process found listening on port {port}")
            return False

        if exclude_pid is not None and pid == exclude_pid:
            logger.debug(f"Port {port} owner PID {pid} is our worker, skipping kill")
            return False

        logger.warning(f"Killing orphan process PID {pid} occupying port {port}")
        try:
            subprocess.run(
                f'taskkill /F /PID {pid}',
                capture_output=True, text=True, timeout=10, shell=True
            )
            # Brief wait for the port to be released
            time.sleep(1)
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.error(f"Failed to kill PID {pid}: {e}")
            return False

    # =========================================================================
    # Python executable discovery
    # =========================================================================

    def _get_python_executable(self) -> str:
        """Get the correct Python executable path.

        When running as a Windows service via pythonservice.exe, sys.executable
        returns the pythonservice.exe path. We need to find the actual Python
        executable in the venv (BUG-03).

        Returns:
            Path to the Python executable
        """
        exe_name = Path(sys.executable).name.lower()
        if exe_name in ('python.exe', 'python', 'python3.exe', 'python3'):
            return sys.executable

        scripts_dir = 'Scripts'
        python_name = 'python.exe'

        candidates = [
            Path(sys.prefix) / scripts_dir / python_name,
            Path(sys.prefix) / 'venv' / scripts_dir / python_name,
            Path(sys.executable).parent / python_name,
        ]

        for candidate in candidates:
            if candidate.exists():
                logger.info(f"Found Python executable: {candidate}")
                return str(candidate)

        logger.warning(
            f"Could not find venv Python in: {[str(c) for c in candidates]}, "
            f"falling back to sys.executable: {sys.executable}"
        )
        return sys.executable


# =============================================================================
# Helper functions
# =============================================================================


def _get_username_for_session(session_id: int) -> Optional[str]:
    """Get username for a WTS session ID.

    Args:
        session_id: Windows Terminal Services session ID

    Returns:
        Username string, or None if lookup fails
    """
    try:
        username = win32ts.WTSQuerySessionInformation(
            win32ts.WTS_CURRENT_SERVER_HANDLE,
            session_id,
            win32ts.WTSUserName
        )
        return username if username else None
    except Exception:
        return None


def _load_user_settings(config_path: Optional[Path]) -> dict:
    """Load user settings from a config file.

    Args:
        config_path: Path to the user's config.json

    Returns:
        Settings dictionary, or empty dict if not available
    """
    if config_path is None or not config_path.exists():
        return {}
    try:
        import json
        return json.loads(config_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"Failed to load config from {config_path}: {e}")
        return {}
