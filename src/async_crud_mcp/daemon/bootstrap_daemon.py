"""Bootstrap daemon for managing MCP server lifecycle.

This daemon monitors user session state and configuration changes to
automatically start/stop the MCP server process as needed.

Incorporates fixes for Windows service context:
- Signal handler wrapped in try/except ValueError (non-main thread)
- Multi-candidate Python executable discovery (pythonservice.exe)
- File-based stderr redirect instead of PIPE (prevents buffer deadlock)
- Loguru enqueue=True with logger.complete() drain on shutdown
- Service-context-aware log directory (ProgramData fallback)

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name (e.g., my-mcp-server)
    async_crud_mcp  - Python package name (e.g., my_mcp_server)

Usage:
    from bootstrap_daemon import BootstrapDaemon
    daemon = BootstrapDaemon()
    asyncio.run(daemon.run())
"""

import asyncio
import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from .paths import get_logs_dir, get_config_file_path


# Configuration - Single APP_NAME convention (ADR-009)
APP_NAME = 'async-crud-mcp'


def configure_logging(log_subdir: Optional[str] = None) -> Path:
    """Configure loguru to write to the platform-appropriate log file.

    Sets up file logging with rotation and optional stderr output.
    Uses enqueue=True for thread-safe async writes; callers MUST call
    ``await logger.complete()`` before process exit to drain the queue.

    Args:
        log_subdir: Optional subdirectory under logs dir (e.g., username
            for per-user dispatcher logs).

    Returns:
        Path to the log file.
    """
    log_dir = get_logs_dir()
    if log_subdir:
        log_dir = log_dir / log_subdir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "daemon.log"

    # Remove default stderr handler and add file handler
    logger.remove()

    # File handler with rotation - always enabled
    logger.add(
        log_file,
        rotation="10 MB",
        retention=3,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        enqueue=True,  # Thread-safe async writes; drain via logger.complete()
    )

    # Console handler - only when running interactively (not as service)
    if sys.stdout is not None and sys.stdout.isatty():
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level:<8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            level="DEBUG",
        )

    return log_file


class BootstrapDaemon:
    """Session-aware daemon that manages MCP server lifecycle.

    The daemon monitors:
    - User session state (active/inactive)
    - Configuration file changes (hot-reload)

    It starts the MCP server when both:
    - User session is active
    - daemon.enabled is True in config

    It stops the server when either condition becomes False.
    """

    def __init__(self) -> None:
        """Initialize the bootstrap daemon and register signal handlers.

        Configures file logging and registers signal handlers. Signal
        registration is wrapped in try/except ValueError because
        signal.signal() raises ValueError when called from a non-main
        thread (expected in Windows service context).
        """
        self.running = True
        self.mcp_process: Optional[subprocess.Popen] = None
        self.config_mtime: Optional[float] = None
        self._stderr_file = None

        # Configure file logging
        self.log_file = configure_logging()
        logger.info("Logging configured, writing to: {}", self.log_file)

        # Register signal handlers (platform-aware)
        # Signal handlers only work in the main thread of the main interpreter.
        # When running as a Windows service, we're not in the main thread, so
        # we skip signal registration and rely on the service framework for
        # shutdown (SvcStop sets self.running = False).
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            if sys.platform != "win32":
                signal.signal(signal.SIGTERM, self._signal_handler)
            logger.debug("Signal handlers registered")
        except ValueError:
            # "signal only works in main thread" - expected in Windows service
            logger.debug("Signal handlers not registered (not in main thread)")

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully.

        Args:
            signum: Signal number received.
            frame: Current stack frame.
        """
        logger.info("Received signal {}, initiating graceful shutdown", signum)
        self.running = False

    async def run(self) -> None:
        """Main daemon loop that monitors session and config state.

        This async method:
        1. Polls user session state
        2. Detects config file changes and reloads settings
        3. Starts/stops MCP server based on conditions
        4. Handles errors gracefully with backoff

        Callers should invoke via ``asyncio.run(daemon.run())``.
        """
        logger.info("Bootstrap daemon starting")

        try:
            while self.running:
                try:
                    # Load current settings (with hot-reload detection)
                    settings = self._load_settings()

                    # Check session state
                    from session_detector import is_user_session_active
                    session_active = is_user_session_active()

                    # Determine if MCP server should be running
                    should_run = session_active and settings.get("daemon", {}).get("enabled", True)

                    # Manage MCP server lifecycle
                    if should_run and self.mcp_process is None:
                        self._start_mcp_server()
                    elif should_run and self.mcp_process is not None:
                        # Check if process crashed
                        if self.mcp_process.poll() is not None:
                            logger.warning(
                                "MCP server process exited with code {}",
                                self.mcp_process.returncode,
                            )
                            self._cleanup_process()
                            # Will be restarted on next iteration
                    elif not should_run and self.mcp_process is not None:
                        self._stop_mcp_server()

                    # Sleep until next poll
                    poll_seconds = settings.get("daemon", {}).get("config_poll_seconds", 3)
                    await asyncio.sleep(poll_seconds)

                except Exception as e:
                    logger.error("Error in daemon main loop: {}", e)
                    await asyncio.sleep(5)  # Back off on error

        finally:
            # Clean up on shutdown
            logger.info("Bootstrap daemon shutting down")
            if self.mcp_process is not None:
                self._stop_mcp_server()
            # Drain loguru's enqueue thread so final messages are written to disk
            await logger.complete()

    def _load_settings(self) -> dict:
        """Load settings and detect config file changes.

        Returns:
            Current settings dictionary.
        """
        config_path = get_config_file_path()

        # Check if config file has changed
        if config_path.exists():
            current_mtime = config_path.stat().st_mtime
            if self.config_mtime is None or current_mtime != self.config_mtime:
                self.config_mtime = current_mtime
                logger.info("Configuration file changed, reloading settings")

            return json.loads(config_path.read_text())

        return {}

    def _get_python_executable(self) -> str:
        """Get the correct Python executable path.

        When running as a Windows service via pythonservice.exe,
        sys.executable returns the pythonservice.exe path, not a Python
        interpreter. We search multiple candidate locations to find the
        actual Python executable in the venv.

        Search order:
        1. sys.executable if it's already python.exe
        2. Scripts/python.exe relative to sys.prefix
        3. venv/Scripts/python.exe relative to sys.prefix
        4. python.exe next to sys.executable's directory

        Returns:
            Path to the Python executable.
        """
        # If sys.executable is a proper python.exe, use it
        exe_name = Path(sys.executable).name.lower()
        if exe_name in ("python.exe", "python", "python3.exe", "python3"):
            return sys.executable

        # Otherwise, we're likely running via pythonservice.exe
        # Build a list of candidate paths to check
        candidates = []

        if sys.platform == "win32":
            scripts_dir = "Scripts"
            python_name = "python.exe"
        else:
            scripts_dir = "bin"
            python_name = "python"

        # Check sys.prefix/Scripts/python.exe (standard venv layout)
        candidates.append(Path(sys.prefix) / scripts_dir / python_name)

        # Check sys.prefix/venv/Scripts/python.exe (when sys.prefix is
        # the parent app directory, not the venv itself)
        candidates.append(Path(sys.prefix) / "venv" / scripts_dir / python_name)

        # Check next to sys.executable (e.g., same dir as pythonservice.exe)
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / python_name)

        for candidate in candidates:
            if candidate.exists():
                logger.info("Found Python executable: {}", candidate)
                return str(candidate)

        # Last resort fallback
        logger.warning(
            "Could not find venv Python in any of: {}",
            [str(c) for c in candidates],
        )
        logger.warning("Falling back to sys.executable: {}", sys.executable)
        return sys.executable

    def _start_mcp_server(self) -> None:
        """Start the MCP server subprocess.

        Launches the server using the Python module entry point.
        Redirects stderr to a log file instead of PIPE to prevent
        pipe buffer deadlock when the server writes large amounts of
        output.
        """
        try:
            python_exe = self._get_python_executable()
            logger.info("Starting MCP server with Python: {}", python_exe)

            # Redirect stderr to a log file instead of PIPE to:
            # 1. Prevent pipe buffer blocking if the server writes a lot
            # 2. Capture startup errors for debugging
            stderr_log = self.log_file.parent / "mcp_server_stderr.log"
            self._stderr_file = open(stderr_log, "w", encoding="utf-8")

            self.mcp_process = subprocess.Popen(
                [python_exe, "-m", "async_crud_mcp.server"],
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
            )
            logger.info("MCP server started with PID {}", self.mcp_process.pid)
            logger.info("MCP server stderr -> {}", stderr_log)
        except Exception as e:
            logger.error("Failed to start MCP server: {}", e)
            self._cleanup_process()

    def _stop_mcp_server(self) -> None:
        """Stop the MCP server subprocess gracefully.

        Sends terminate (SIGTERM on Unix, TerminateProcess on Windows)
        and waits up to 5 seconds. Falls back to kill if timeout exceeded.
        Always cleans up the stderr file handle in the finally block.
        """
        if self.mcp_process is None:
            return

        try:
            logger.info("Stopping MCP server")
            self.mcp_process.terminate()
            self.mcp_process.wait(timeout=5)
            logger.info("MCP server stopped")
        except subprocess.TimeoutExpired:
            logger.warning("MCP server did not stop gracefully, killing")
            self.mcp_process.kill()
            self.mcp_process.wait()
        except Exception as e:
            logger.error("Error stopping MCP server: {}", e)
        finally:
            self._cleanup_process()

    def _cleanup_process(self) -> None:
        """Clean up process and stderr file handle."""
        self.mcp_process = None
        if self._stderr_file is not None:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None


# =============================================================================
# CLI for direct execution
# =============================================================================

if __name__ == "__main__":
    daemon = BootstrapDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass
