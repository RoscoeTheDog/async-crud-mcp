"""Windows daemon implementation.

This package provides Windows-specific daemon functionality using Windows Services
and the pywin32 library. The main components are:

- windows_service: Windows Service wrapper with install/uninstall/start/stop
- dispatcher: Multi-user dispatcher for managing per-user MCP server workers
- session_detector: WTS API session detection utilities

Public API:
    install_service: Install the Windows service
    uninstall_service: Uninstall the Windows service
    start_service: Start the Windows service
    stop_service: Stop the Windows service
    DaemonService: Windows Service class (for pythonservice.exe)
    MultiUserDispatcher: Per-user worker process manager
"""

# Import public API from windows_service
from .windows_service import (
    DaemonService,
    install_service,
    uninstall_service,
    start_service,
    stop_service,
)

# Import dispatcher for internal use
from .dispatcher import MultiUserDispatcher

# Import session detection utilities
from .session_detector import (
    get_active_sessions,
    is_user_session_active,
    get_session_details,
)

__all__ = [
    # Service management
    'DaemonService',
    'install_service',
    'uninstall_service',
    'start_service',
    'stop_service',
    # Dispatcher
    'MultiUserDispatcher',
    # Session detection
    'get_active_sessions',
    'is_user_session_active',
    'get_session_details',
]
