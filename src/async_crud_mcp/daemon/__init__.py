"""Daemon infrastructure for async-crud-mcp.

This package provides cross-platform daemon/service support including:
- Path management (config, logs, data directories)
- Logging setup with rotation and async safety
- Graceful shutdown handling
- Session detection (active user sessions)
- Configuration initialization and watching
- Health checking
- Platform-specific installers
- Bootstrap daemon orchestration
"""

from .bootstrap_daemon import BootstrapDaemon
from .config_init import init_config, load_settings_from_file
from .config_watcher import ConfigWatcher, ResilientConfigLoader
from .graceful_shutdown import (
    AsyncShutdownHandler,
    ShutdownHandler,
    graceful_stop,
    shutdown_context,
)
from .health import check_health
from .installer import get_installer
from .logging_setup import get_logger, setup_logging
from .paths import (
    APP_NAME,
    get_config_dir,
    get_config_file_path,
    get_data_dir,
    get_install_dir,
    get_logs_dir,
    get_shared_dir,
    get_shared_python_dir,
    get_shared_uv_dir,
    get_user_config_file_path,
    get_user_dir,
    get_user_logs_dir,
    get_venv_dir,
)
from .session_detector import get_active_sessions, is_user_session_active

__all__ = [
    # Bootstrap
    'BootstrapDaemon',
    # Config
    'init_config',
    'load_settings_from_file',
    'ConfigWatcher',
    'ResilientConfigLoader',
    # Shutdown
    'AsyncShutdownHandler',
    'ShutdownHandler',
    'graceful_stop',
    'shutdown_context',
    # Health
    'check_health',
    # Installer
    'get_installer',
    # Logging
    'get_logger',
    'setup_logging',
    # Paths
    'APP_NAME',
    'get_config_dir',
    'get_config_file_path',
    'get_data_dir',
    'get_install_dir',
    'get_logs_dir',
    'get_shared_dir',
    'get_shared_python_dir',
    'get_shared_uv_dir',
    'get_user_config_file_path',
    'get_user_dir',
    'get_user_logs_dir',
    'get_venv_dir',
    # Session
    'get_active_sessions',
    'is_user_session_active',
]
