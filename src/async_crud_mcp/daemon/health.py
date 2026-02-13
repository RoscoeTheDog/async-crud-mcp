"""Health check functionality for the daemon service.

Provides application-level health checking beyond simple service status.
Verifies config readability, daemon enabled status, logs directory,
and port connectivity (ADR-012).

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name (e.g., my-mcp-server)
    async_crud_mcp  - Python package name (e.g., my_mcp_server)
    8720  - Default port number (e.g., 8422)
"""

import json
import socket
from typing import Any

from .paths import get_config_file_path, get_logs_dir


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


def check_health() -> dict[str, Any]:
    """Check the health status of the daemon.

    Verifies:
    - Config file is readable and valid JSON
    - Daemon enabled status
    - Logs directory exists
    - Port is accepting connections (if daemon is enabled, ADR-012)

    Returns:
        Dictionary with health check results containing:
        - status: 'healthy', 'degraded', or 'unhealthy'
        - config_readable: bool
        - daemon_enabled: bool or None
        - logs_dir_exists: bool
        - port_listening: bool or None (None if check not applicable)
        - host: configured host (if config readable)
        - port: configured port (if config readable)
        - message: str describing the overall status
    """
    result = {
        'status': 'healthy',
        'config_readable': False,
        'daemon_enabled': None,
        'logs_dir_exists': False,
        'port_listening': None,
        'host': None,
        'port': None,
        'message': '',
    }

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

    # Check logs directory
    logs_dir = get_logs_dir()
    result['logs_dir_exists'] = logs_dir.exists()

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
