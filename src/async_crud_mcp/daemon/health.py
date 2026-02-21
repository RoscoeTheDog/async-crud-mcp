"""Health check functionality for the daemon service.

Provides application-level health checking beyond simple service status.
Verifies config readability, daemon enabled status, logs directory,
port connectivity (ADR-012), Python version, dependency availability,
disk space, uptime, and circuit breaker state (ADR-013).

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name (e.g., my-mcp-server)
    async_crud_mcp  - Python package name (e.g., my_mcp_server)
    8720  - Default port number (e.g., 8422)
"""

import json
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from .paths import get_config_file_path, get_logs_dir

# Module-level start time for uptime tracking
_start_time = time.time()


def _is_port_listening(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is accepting connections.

    Args:
        host: Host address to check
        port: Port number to check
        timeout: Connection timeout in seconds

    Returns:
        True if something is listening on the port
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    finally:
        sock.close()


def _check_python_version() -> dict[str, Any]:
    """Check if the Python version meets minimum requirements (>= 3.10).

    Returns:
        Dict with 'ok' bool, 'version' string, and optional 'message'
    """
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    ok = version >= (3, 10)
    result = {'ok': ok, 'version': version_str}
    if not ok:
        result['message'] = f"Python >= 3.10 required, found {version_str}"
    return result


def _check_dependency_available(package_name: str) -> dict[str, Any]:
    """Check if a Python package is importable.

    Args:
        package_name: Dotted package name to try importing

    Returns:
        Dict with 'ok' bool and optional 'version' or 'message'
    """
    try:
        mod = __import__(package_name)
        version = getattr(mod, '__version__', 'unknown')
        return {'ok': True, 'version': version}
    except ImportError as e:
        return {'ok': False, 'message': str(e)}


def _check_disk_space(path: str, min_mb: int = 100) -> dict[str, Any]:
    """Check available disk space at the given path.

    Args:
        path: Directory path to check
        min_mb: Minimum free space in MB to consider healthy

    Returns:
        Dict with 'ok' bool, 'free_mb' float, and optional 'message'
    """
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
        ok = free_mb >= min_mb
        result: dict[str, Any] = {'ok': ok, 'free_mb': round(free_mb, 1)}
        if not ok:
            result['message'] = (
                f"Low disk space: {free_mb:.0f}MB free (minimum {min_mb}MB)"
            )
        return result
    except OSError as e:
        return {'ok': False, 'free_mb': 0, 'message': str(e)}


def _get_uptime_seconds() -> float:
    """Get seconds since this module was first imported.

    Returns:
        Uptime in seconds
    """
    return time.time() - _start_time


def _read_circuit_breaker_state(logs_dir: str) -> dict[str, Any] | None:
    """Read ADR-013 circuit breaker state from disk.

    Args:
        logs_dir: Path to the logs directory

    Returns:
        Circuit breaker state dict, or None if not present
    """
    try:
        import os
        state_file = os.path.join(logs_dir, 'circuit_breaker_state.json')
        if not os.path.exists(state_file):
            return None
        with open(state_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def check_health() -> dict[str, Any]:
    """Check the health status of the daemon.

    Verifies:
    - Config file is readable and valid JSON
    - Daemon enabled status
    - Logs directory exists
    - Port is accepting connections (if daemon is enabled, ADR-012)
    - Python version >= 3.10
    - Package dependency is importable
    - Disk space at logs directory
    - Module uptime
    - Circuit breaker state (ADR-013)

    Returns:
        Dictionary with health check results containing:
        - status: 'healthy', 'degraded', or 'unhealthy'
        - config_readable: bool
        - daemon_enabled: bool or None
        - logs_dir_exists: bool
        - port_listening: bool or None (None if check not applicable)
        - host: configured host (if config readable)
        - port: configured port (if config readable)
        - python: dict with version check results
        - dependency_available: dict with import check results
        - disk_space: dict with disk space check results
        - uptime_seconds: float
        - circuit_breaker: dict or None
        - message: str describing the overall status
    """
    result: dict[str, Any] = {
        'status': 'healthy',
        'config_readable': False,
        'daemon_enabled': None,
        'logs_dir_exists': False,
        'port_listening': None,
        'host': None,
        'port': None,
        'python': None,
        'dependency_available': None,
        'disk_space': None,
        'uptime_seconds': None,
        'circuit_breaker': None,
        'message': '',
    }

    # Check Python version
    result['python'] = _check_python_version()

    # Check dependency
    result['dependency_available'] = _check_dependency_available(
        'async_crud_mcp'
    )

    # Uptime
    result['uptime_seconds'] = round(_get_uptime_seconds(), 1)

    # Check config file
    config_path = get_config_file_path()
    daemon_config = {}
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            result['config_readable'] = True
            daemon_config = config.get('daemon', {})
            result['daemon_enabled'] = daemon_config.get('enabled', False)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            result['status'] = 'degraded'
            result['message'] = f'Config file error: {e}'
    else:
        result['status'] = 'degraded'
        result['message'] = 'Config file not found'

    # Check logs directory (create if missing)
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    result['logs_dir_exists'] = logs_dir.exists()

    # Check disk space at logs directory (fall back to home dir if path doesn't exist)
    disk_check_path = str(logs_dir) if logs_dir.exists() else str(Path.home())
    result['disk_space'] = _check_disk_space(disk_check_path)
    if result['disk_space'] and not result['disk_space']['ok']:
        if result['status'] == 'healthy':
            result['status'] = 'degraded'
            result['message'] = result['disk_space'].get('message', '')

    # Check circuit breaker state (ADR-013)
    result['circuit_breaker'] = _read_circuit_breaker_state(str(logs_dir))

    # Check port connectivity (only if daemon is enabled, ADR-012)
    host = daemon_config.get('host', '127.0.0.1')
    port = daemon_config.get('port', 8720)
    result['host'] = host
    result['port'] = port

    if result['daemon_enabled']:
        listening = _is_port_listening(host, port)
        result['port_listening'] = listening
        if not listening:
            result['status'] = 'unhealthy'
            result['message'] = (
                f'Port {port} is not listening on {host} - '
                f'server may have failed to start'
            )
            return result

    # Set overall status
    if result['status'] == 'healthy':
        if result['daemon_enabled']:
            result['message'] = 'Daemon is enabled and healthy'
        else:
            result['message'] = 'Daemon is disabled'
            result['status'] = 'degraded'

    return result
