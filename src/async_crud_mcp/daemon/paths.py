"""Cross-platform path helpers for async-crud-mcp.

This module provides platform-aware functions for locating configuration,
data, logs, and installation directories according to OS conventions.

All functions return Path objects. Directories are NOT created automatically;
callers should call ``path.mkdir(parents=True, exist_ok=True)`` as needed.
"""

import os
import sys
from pathlib import Path

# Local APP_NAME constant as fallback (ADR-009 single name convention)
_APP_NAME_DEFAULT = 'async-crud-mcp'

try:
    from ..config import APP_NAME
except ImportError:
    APP_NAME = _APP_NAME_DEFAULT

__all__ = [
    'APP_NAME',
    'get_install_dir',
    'get_config_dir',
    'get_logs_dir',
    'get_data_dir',
    'get_cache_dir',
    'get_shared_dir',
    'get_shared_python_dir',
    'get_shared_uv_dir',
    'get_user_dir',
    'get_venv_dir',
    'get_config_file_path',
    'get_user_config_file_path',
    'get_user_logs_dir',
]


def _get_platform() -> str:
    """Detect the current platform.

    Returns:
        'windows', 'darwin', or 'linux'
    """
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'darwin'
    else:
        return 'linux'


def _get_xdg_path(xdg_var: str, default_subpath: str) -> Path:
    """Get XDG-compliant path with environment variable support.

    Args:
        xdg_var: XDG environment variable name (e.g., 'XDG_CONFIG_HOME')
        default_subpath: Default path relative to home (e.g., '.config')

    Returns:
        Path with APP_NAME appended
    """
    xdg_base = os.environ.get(xdg_var)
    if xdg_base:
        return Path(xdg_base) / APP_NAME
    return Path.home() / default_subpath / APP_NAME


def _is_windows_service_context() -> bool:
    """Detect if running as a Windows service (LocalSystem account).

    When a Windows service runs as LocalSystem, LOCALAPPDATA points to
    the system profile directory. This function detects that case so
    callers can fall back to ProgramData.

    Returns:
        True if LOCALAPPDATA points to the system profile directory,
        indicating the process is running as LocalSystem.
    """
    localappdata = os.environ.get('LOCALAPPDATA', '')
    return 'systemprofile' in localappdata.lower()


def get_install_dir() -> Path:
    """Get platform-appropriate installation directory.

    Returns:
        Path to installation directory (not created automatically)
        - Windows: C:\\Program Files\\async-crud-mcp or user-local equivalent
        - macOS: ~/Applications/async-crud-mcp
        - Linux: ~/.local/bin/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        program_files = os.environ.get('PROGRAMFILES')
        if program_files:
            return Path(program_files) / APP_NAME
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / 'Programs' / APP_NAME
        return Path.home() / 'AppData' / 'Local' / 'Programs' / APP_NAME

    elif platform == 'darwin':
        return Path.home() / 'Applications' / APP_NAME

    else:  # linux
        return Path.home() / '.local' / 'bin' / APP_NAME


def get_config_dir() -> Path:
    """Get platform-appropriate configuration directory.

    Returns:
        Path to configuration directory (not created automatically)
        - Windows: %LOCALAPPDATA%\\async-crud-mcp\\config
        - macOS: ~/Library/Preferences/async-crud-mcp
        - Linux: XDG_CONFIG_HOME/async-crud-mcp or ~/.config/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / APP_NAME / 'config'
        return Path.home() / 'AppData' / 'Local' / APP_NAME / 'config'

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Preferences' / APP_NAME

    else:  # linux
        return _get_xdg_path('XDG_CONFIG_HOME', '.config')


def get_logs_dir() -> Path:
    """Get platform-appropriate logs directory.

    On Windows, falls back to ProgramData when running as a Windows service
    under LocalSystem account (detected by LOCALAPPDATA pointing to the
    system profile directory).

    Returns:
        Path to logs directory (not created automatically)
        - Windows: %LOCALAPPDATA%\\async-crud-mcp\\logs or %PROGRAMDATA%\\async-crud-mcp\\logs
        - macOS: ~/Library/Logs/async-crud-mcp
        - Linux: XDG_STATE_HOME/async-crud-mcp/logs or ~/.local/state/async-crud-mcp/logs
    """
    platform = _get_platform()

    if platform == 'windows':
        if not _is_windows_service_context():
            localappdata = os.environ.get('LOCALAPPDATA')
            if localappdata:
                return Path(localappdata) / APP_NAME / 'logs'
        # Fallback for Windows services running as LocalSystem
        programdata = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
        return Path(programdata) / APP_NAME / 'logs'

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Logs' / APP_NAME

    else:  # linux
        return _get_xdg_path('XDG_STATE_HOME', '.local/state') / 'logs'


def get_data_dir() -> Path:
    """Get platform-appropriate data directory.

    Returns:
        Path to data directory (not created automatically)
        - Windows: %LOCALAPPDATA%\\async-crud-mcp\\data
        - macOS: ~/Library/Application Support/async-crud-mcp
        - Linux: XDG_DATA_HOME/async-crud-mcp or ~/.local/share/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / APP_NAME / 'data'
        return Path.home() / 'AppData' / 'Local' / APP_NAME / 'data'

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP_NAME

    else:  # linux
        return _get_xdg_path('XDG_DATA_HOME', '.local/share')


def get_cache_dir() -> Path:
    """Get platform-appropriate cache directory.

    Returns:
        Path to cache directory (not created automatically)
        - Windows: %LOCALAPPDATA%\\async-crud-mcp\\cache
        - macOS: ~/Library/Caches/async-crud-mcp
        - Linux: XDG_CACHE_HOME/async-crud-mcp or ~/.cache/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / APP_NAME / 'cache'
        return Path.home() / 'AppData' / 'Local' / APP_NAME / 'cache'

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / APP_NAME

    else:  # linux
        return _get_xdg_path('XDG_CACHE_HOME', '.cache')


def get_shared_dir() -> Path:
    """Get platform-appropriate system-wide shared directory.

    Returns:
        Path to shared directory (not created automatically)
        - Windows: C:\\ProgramData\\async-crud-mcp
        - macOS: /Library/Application Support/async-crud-mcp
        - Linux: /opt/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        programdata = os.environ.get('PROGRAMDATA')
        if programdata:
            return Path(programdata) / APP_NAME
        return Path('C:/ProgramData') / APP_NAME

    elif platform == 'darwin':
        return Path('/Library/Application Support') / APP_NAME

    else:  # linux
        return Path('/opt') / APP_NAME


def get_shared_python_dir() -> Path:
    """Get platform-appropriate system-wide Python directory.

    Returns:
        Path to shared Python directory (for embedded Python installation).
    """
    return get_shared_dir() / 'python'


def get_shared_uv_dir() -> Path:
    """Get platform-appropriate uv directory.

    Returns:
        Path to uv directory (not created automatically)
        - Windows: shared_dir/uv (system-wide)
        - macOS/Linux: user data dir / uv
    """
    platform = _get_platform()

    if platform == 'windows':
        programdata = os.environ.get('PROGRAMDATA')
        if programdata:
            return get_shared_dir() / 'uv'
        return get_user_dir() / 'uv'

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP_NAME / 'uv'

    else:  # linux
        return _get_xdg_path('XDG_DATA_HOME', '.local/share') / 'uv'


def get_user_dir() -> Path:
    """Get platform-appropriate per-user base directory.

    Returns:
        Path to per-user directory (not created automatically)
        - Windows: %LOCALAPPDATA%\\async-crud-mcp
        - macOS: ~/Library/Application Support/async-crud-mcp
        - Linux: ~/.local/share/async-crud-mcp
    """
    platform = _get_platform()

    if platform == 'windows':
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / APP_NAME
        return Path.home() / 'AppData' / 'Local' / APP_NAME

    elif platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP_NAME

    else:  # linux
        return _get_xdg_path('XDG_DATA_HOME', '.local/share')


def get_venv_dir() -> Path:
    """Get platform-appropriate per-user virtual environment directory.

    Returns:
        Path to virtual environment directory (not created automatically).
    """
    return get_user_dir() / 'venv'


def get_config_file_path() -> Path:
    """Get platform-appropriate configuration file path.

    Returns:
        Path to config.json file (not created automatically).
    """
    return get_config_dir() / 'config.json'


def _get_user_profile_path(username: str) -> Path:
    """Get user profile path via Windows registry (works from LocalSystem).

    Looks up the ProfileImagePath for the given username's SID in the
    Windows registry ProfileList.

    Args:
        username: Windows username to look up

    Returns:
        Path to the user's profile directory (e.g., C:\\Users\\Alice)

    Raises:
        OSError: If the user cannot be found in the registry
        ImportError: If not running on Windows or pywin32 unavailable
    """
    if sys.platform != 'win32':
        raise ImportError("_get_user_profile_path is only available on Windows")

    import winreg
    try:
        import win32security
    except ImportError as e:
        raise ImportError(
            "pywin32 is required for user profile lookup. "
            "Install with: pip install pywin32"
        ) from e

    sid_obj, _, _ = win32security.LookupAccountName(None, username)
    sid_str = win32security.ConvertSidToStringSid(sid_obj)

    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        rf"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\{sid_str}"
    )
    try:
        value, _ = winreg.QueryValueEx(key, "ProfileImagePath")
        return Path(os.path.expandvars(value))
    finally:
        winreg.CloseKey(key)


def get_user_config_file_path(username: str) -> Path:
    """Get config file path for a specific user (used by dispatcher).

    On Windows, resolves the user's profile directory via registry
    and constructs the LOCALAPPDATA-equivalent path.

    Args:
        username: Windows username whose config path to resolve

    Returns:
        Path to the user's config.json file
    """
    profile_path = _get_user_profile_path(username)
    return profile_path / 'AppData' / 'Local' / APP_NAME / 'config' / 'config.json'


def get_user_logs_dir(username: str) -> Path:
    """Get per-user logs directory under ProgramData (for service context).

    Used by the multi-user dispatcher to create per-user log directories
    under the shared ProgramData location.

    Args:
        username: Windows username for the log subdirectory

    Returns:
        Path to per-user logs directory
        e.g., C:\\ProgramData\\async-crud-mcp\\logs\\{username}
    """
    programdata = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
    return Path(programdata) / APP_NAME / 'logs' / username
