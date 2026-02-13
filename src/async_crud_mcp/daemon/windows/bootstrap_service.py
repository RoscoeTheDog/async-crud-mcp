"""Windows Service wrapper for MCP daemon with Multi-User Dispatcher.

This module provides a pywin32-based Windows Service implementation that:
- Runs as a single system-wide service (async-crud-mcp-daemon)
- Uses a Multi-User Dispatcher to manage per-user worker processes
- Responds to session logon/logoff events via SvcOtherEx
- Auto-starts on system boot (SERVICE_AUTO_START)

Architecture:
    Windows Service (LocalSystem) - single system-wide service
    "Dispatcher"
    - SESSION_LOGON/LOGOFF events via SvcOtherEx
    - Manages per-user worker processes via CreateProcessAsUser
    - Logs to ProgramData (service context)
    - Service name: async-crud-mcp-daemon (no user suffix)

Key fixes from reference implementation:
    - BUG-01: Reports SERVICE_RUNNING immediately to prevent SCM timeout (error 1053)
    - BUG-02/10: Uses WindowsSelectorEventLoopPolicy to avoid signal.signal() ValueError
              in non-main thread (Windows service context)
    - BUG-03: Multi-candidate Python executable discovery (pythonservice.exe -> python.exe)
    - BUG-07: Wraps SvcDoRun in try/except to log errors to Windows Event Log
    - BUG-11: Uses direct win32service.CreateService() API instead of HandleCommandLine
              (HandleCommandLine calls sys.exit() instead of raising exceptions)
    - GAP-4: Direct CreateService with PythonClass registry key setup
    - GAP-6: Manual event loop with WindowsSelectorEventLoopPolicy

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name
    async_crud_mcp  - Python package name

Usage:
    Called by pythonservice.exe when Windows starts the service.
    Install/uninstall via the CLI: async-crud-mcp bootstrap install|uninstall
"""

import asyncio
import sys
from pathlib import Path

# Platform check - must happen before pywin32 imports
if sys.platform != 'win32':
    raise ImportError(
        "bootstrap_service module is only available on Windows. "
        f"Current platform: {sys.platform}"
    )

# pywin32 availability check
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError as e:
    raise ImportError(
        "pywin32 is required for Windows service functionality. "
        "Install with: pip install pywin32"
    ) from e

from loguru import logger

# =============================================================================
# Configuration - Single APP_NAME convention (ADR-009)
# =============================================================================

APP_NAME = 'async-crud-mcp'
PACKAGE_NAME = 'async_crud_mcp'
SERVICE_NAME = f'{APP_NAME}-daemon'
SERVICE_DISPLAY_NAME = f'{APP_NAME} Daemon'
SERVICE_DESCRIPTION = f'MCP server daemon for {APP_NAME} - multi-user dispatcher'

# Windows Terminal Services session change constants
WTS_SESSION_LOGON = 5
WTS_SESSION_LOGOFF = 6


# =============================================================================
# Service Class - Multi-User Dispatcher
# =============================================================================

class DaemonService(win32serviceutil.ServiceFramework):
    """Windows Service that runs a Multi-User Dispatcher.

    Single system-wide service that manages per-user MCP server workers.
    Accepts session change notifications to detect user logon/logoff.
    """

    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        """Initialize the Windows service.

        Args:
            args: Service framework arguments from Windows SCM
        """
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.dispatcher = None

    def GetAcceptedControls(self):
        """Declare that we accept session change notifications.

        Returns:
            Bitmask of accepted service controls including SESSION_CHANGE
        """
        rc = win32serviceutil.ServiceFramework.GetAcceptedControls(self)
        rc |= win32service.SERVICE_ACCEPT_SESSIONCHANGE
        return rc

    def SvcOtherEx(self, control, event_type, data):
        """Handle extended service control events.

        Processes SESSION_CHANGE events to detect user logon and logoff,
        forwarding them to the dispatcher.

        Args:
            control: Service control code
            event_type: Event type within the control
            data: Tuple containing event-specific data (session_id for session events)
        """
        if control == win32service.SERVICE_CONTROL_SESSIONCHANGE:
            if data and len(data) > 0:
                session_id = data[0]
            else:
                return

            if event_type == WTS_SESSION_LOGON:
                if self.dispatcher:
                    self.dispatcher.on_session_logon(session_id)
            elif event_type == WTS_SESSION_LOGOFF:
                if self.dispatcher:
                    self.dispatcher.on_session_logoff(session_id)

    def SvcStop(self):
        """Handle service stop request from Windows SCM."""
        logger.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

        if self.dispatcher is not None:
            self.dispatcher.running = False

    def SvcDoRun(self):
        """Main service entry point - runs the multi-user dispatcher.

        This method:
        1. Reports SERVICE_RUNNING to SCM immediately (BUG-01: prevents error 1053)
        2. Logs service start to Windows event log
        3. Creates MultiUserDispatcher instance
        4. Runs dispatcher async loop with manual event loop (BUG-02/10: GAP-6)
        5. Logs service stop to Windows event log

        Wrapped in try/except to log errors to Windows Event Log (BUG-07).
        """
        # CRITICAL: Report SERVICE_RUNNING immediately to prevent SCM timeout
        # The SCM expects this within ~30 seconds or it will timeout (error 1053)
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        # Log start to Windows event log
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        logger.info(f"Service {self._svc_name_} starting")

        # Create dispatcher
        try:
            from .dispatcher import MultiUserDispatcher
            self.dispatcher = MultiUserDispatcher()
        except Exception as e:
            logger.error(f"Failed to create dispatcher: {e}")
            servicemanager.LogErrorMsg(f"Failed to create dispatcher: {e}")
            return

        # Run async dispatcher loop
        # NOTE: We can't use asyncio.run() or the default ProactorEventLoop in a
        # Windows service because they try to install signal handlers, which fails
        # with "set_wakeup_fd only works in main thread" (BUG-02, BUG-10).
        #
        # Solution: Use WindowsSelectorEventLoopPolicy which doesn't use signals,
        # and create the event loop manually (GAP-6, ADR-011).
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.dispatcher.run())
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Service error: {e}")
            servicemanager.LogErrorMsg(f"Service error: {e}")

        # Log stop to Windows event log
        logger.info(f"Service {self._svc_name_} stopped")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, '')
        )


# =============================================================================
# Service Management Functions (GAP-4: Direct CreateService API)
# =============================================================================

def install_service(account=None):
    """Install the Windows service using direct win32service.CreateService() API.

    This replaces HandleCommandLine which calls sys.exit() instead of raising
    exceptions (BUG-11). Uses direct CreateService for reliable error handling.

    Registers the service with Windows SCM with SERVICE_AUTO_START to run
    at system boot. Writes PythonClass registry key so pythonservice.exe
    knows which class to instantiate.

    Args:
        account: Optional Windows account to run service as.
                 If None (default), runs as LocalSystem account.

    Raises:
        PermissionError: If not running as Administrator
        FileNotFoundError: If pythonservice.exe not found
        OSError: If service creation fails
    """
    import winreg
    import time

    svc_name = DaemonService._svc_name_
    svc_display = DaemonService._svc_display_name_
    svc_desc = DaemonService._svc_description_

    # Get pythonservice.exe path - it should be in the venv root
    # (GAP-5: copied there by installer's _configure_pythonservice step)
    python_exe = sys.executable
    venv_dir = Path(python_exe).parent.parent
    pythonservice_exe = venv_dir / 'pythonservice.exe'

    if not pythonservice_exe.exists():
        # Fallback: check in Scripts directory
        pythonservice_exe = venv_dir / 'Scripts' / 'pythonservice.exe'

    if not pythonservice_exe.exists():
        raise FileNotFoundError(
            f"pythonservice.exe not found. Expected at {venv_dir / 'pythonservice.exe'}"
        )

    binary_path = f'"{pythonservice_exe}"'

    # CRITICAL: serviceClassString must be the fully-qualified class name
    # pythonservice.exe reads this from the PythonClass registry key
    service_class_string = f'{__name__}.{DaemonService.__name__}'

    try:
        hs = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        try:
            # Remove existing service if present
            try:
                existing = win32service.OpenService(
                    hs, svc_name, win32service.SERVICE_ALL_ACCESS
                )
                win32service.CloseServiceHandle(existing)
                logger.info(f"Service {svc_name} already exists, removing...")
                win32serviceutil.RemoveService(svc_name)
                time.sleep(1)
            except Exception:
                pass  # Service doesn't exist, that's fine

            # Create the service
            h = win32service.CreateService(
                hs,
                svc_name,
                svc_display,
                win32service.SERVICE_ALL_ACCESS,
                win32service.SERVICE_WIN32_OWN_PROCESS,
                win32service.SERVICE_AUTO_START,
                win32service.SERVICE_ERROR_NORMAL,
                binary_path,
                None,   # load order group
                False,  # bFetchTag
                None,   # dependencies
                account,  # service account (None = LocalSystem)
                None,   # password
            )
            win32service.CloseServiceHandle(h)

            # Set description via ChangeServiceConfig2
            try:
                hs2 = win32service.OpenService(
                    win32service.OpenSCManager(
                        None, None, win32service.SC_MANAGER_ALL_ACCESS
                    ),
                    svc_name,
                    win32service.SERVICE_CHANGE_CONFIG,
                )
                try:
                    win32service.ChangeServiceConfig2(
                        hs2,
                        win32service.SERVICE_CONFIG_DESCRIPTION,
                        svc_desc,
                    )
                finally:
                    win32service.CloseServiceHandle(hs2)
            except Exception as e:
                logger.warning(f"Could not set service description: {e}")

            # Write PythonClass to registry - CRITICAL for pythonservice.exe
            reg_path = f"SYSTEM\\CurrentControlSet\\Services\\{svc_name}\\PythonClass"
            try:
                key = winreg.CreateKeyEx(
                    winreg.HKEY_LOCAL_MACHINE, reg_path, 0, winreg.KEY_WRITE
                )
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, service_class_string)
                winreg.CloseKey(key)
                logger.info(f"Set PythonClass registry value to: {service_class_string}")
            except Exception as e:
                logger.error(f"Failed to set PythonClass registry: {e}")
                raise

        finally:
            win32service.CloseServiceHandle(hs)

        logger.info(f"Service {svc_name} installed successfully")

    except win32service.error as e:
        error_code = e.winerror
        if error_code == 5:  # ACCESS_DENIED
            raise PermissionError(
                "Access denied. Run as Administrator to install the service."
            ) from e
        elif error_code == 1073:  # SERVICE_EXISTS
            raise RuntimeError(
                f"Service {svc_name} already exists. Uninstall first."
            ) from e
        else:
            raise OSError(f"Failed to install service: {e}") from e


def uninstall_service():
    """Uninstall the Windows service.

    Raises:
        OSError: If removal fails
    """
    try:
        win32serviceutil.HandleCommandLine(
            DaemonService,
            argv=[sys.argv[0], 'remove']
        )
        logger.info(f"Service {DaemonService._svc_name_} uninstalled")
    except Exception as e:
        logger.error(f"Failed to uninstall service: {e}")
        raise


def start_service(timeout=30):
    """Start the Windows service and wait for it to reach RUNNING state.

    Args:
        timeout: Maximum seconds to wait for service to start (default: 30)

    Raises:
        RuntimeError: If service stops unexpectedly during startup
        TimeoutError: If service doesn't reach RUNNING state within timeout
    """
    import time

    svc_name = DaemonService._svc_name_

    win32serviceutil.StartService(svc_name)
    logger.info(f"Start command sent to {svc_name}")

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            status = win32serviceutil.QueryServiceStatus(svc_name)
            if status[1] == win32service.SERVICE_RUNNING:
                logger.info(f"Service {svc_name} started successfully")
                return
            elif status[1] == win32service.SERVICE_STOPPED:
                raise RuntimeError(
                    f"Service {svc_name} stopped unexpectedly during startup. "
                    "Check Windows Event Log for details."
                )
            time.sleep(0.5)
        except RuntimeError:
            raise
        except Exception:
            time.sleep(0.5)

    raise TimeoutError(
        f"Service {svc_name} did not start within {timeout} seconds."
    )


def stop_service():
    """Stop the Windows service.

    Raises:
        OSError: If stop fails
    """
    try:
        win32serviceutil.StopService(DaemonService._svc_name_)
        logger.info(f"Service {DaemonService._svc_name_} stopped")
    except Exception as e:
        logger.error(f"Failed to stop service: {e}")
        raise


# =============================================================================
# Entry point for pythonservice.exe
# =============================================================================

if __name__ == '__main__':
    # Support command-line service management
    # Usage: python -m async_crud_mcp.daemon.windows.bootstrap_service install|start|stop|remove
    win32serviceutil.HandleCommandLine(DaemonService)
