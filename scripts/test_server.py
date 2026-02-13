#!/usr/bin/env python3
"""Post-install verification for async-crud-mcp."""

import argparse
import glob
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_status(check_name, status, message=""):
    """Print check status with color.

    Args:
        check_name: Name of the check
        status: 'pass', 'fail', or 'skip'
        message: Optional message to display
    """
    if status == 'pass':
        status_str = f"{Colors.GREEN}[PASS]{Colors.RESET}"
    elif status == 'skip':
        status_str = f"{Colors.YELLOW}[SKIP]{Colors.RESET}"
    else:
        status_str = f"{Colors.RED}[FAIL]{Colors.RESET}"

    print(f"{status_str} {check_name}")
    if message:
        print(f"      {message}")


def check_python_version():
    """Check if Python version is 3.12+."""
    print(f"\n{Colors.BOLD}Checking Python version...{Colors.RESET}")

    version = sys.version_info
    passed = version >= (3, 12)

    version_str = f"{version.major}.{version.minor}.{version.micro}"
    status = 'pass' if passed else 'fail'
    print_status(
        "Python Version",
        status,
        f"Found Python {version_str} {'(OK)' if passed else '(need 3.12+)'}"
    )

    return status


def check_package_import():
    """Check if async-crud-mcp package can be imported."""
    print(f"\n{Colors.BOLD}Checking package installation...{Colors.RESET}")

    try:
        import async_crud_mcp
        status = 'pass'
        version = getattr(async_crud_mcp, "__version__", "unknown")
        print_status("Package Import", status, f"async-crud-mcp version {version}")
    except ImportError as e:
        status = 'fail'
        print_status("Package Import", status, f"Import failed: {e}")

    return status


def get_config_paths():
    """Get platform-specific config paths."""
    system = platform.system()

    if system == "Windows":
        import os
        appdata = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        config_dir = Path(appdata) / "async-crud-mcp" / "config"
    elif system == "Darwin":
        config_dir = Path.home() / "Library" / "Application Support" / "async-crud-mcp" / "config"
    else:
        import os
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        config_dir = Path(xdg_config_home) / "async-crud-mcp"

    return config_dir / "config.json"


def check_config_file():
    """Check if config file exists and is valid."""
    print(f"\n{Colors.BOLD}Checking configuration...{Colors.RESET}")

    config_path = get_config_paths()

    if not config_path.exists():
        print_status("Config File", 'fail', f"Not found at {config_path}")
        return 'fail'

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        host = config.get("host", "N/A")
        port = config.get("port", "N/A")

        print_status("Config File", 'pass', f"Found at {config_path}")
        print(f"      Host: {host}, Port: {port}")
        return 'pass'

    except json.JSONDecodeError as e:
        print_status("Config File", 'fail', f"Invalid JSON: {e}")
        return 'fail'
    except Exception as e:
        print_status("Config File", 'fail', f"Error reading config: {e}")
        return 'fail'


def check_daemon_service():
    """Check if daemon service is installed and running."""
    print(f"\n{Colors.BOLD}Checking daemon service...{Colors.RESET}")

    system = platform.system()

    try:
        if system == "Windows":
            # Check Windows service
            result = subprocess.run(
                ["sc", "query", "AsyncCrudMCP"],
                capture_output=True,
                text=True
            )
            installed = result.returncode == 0
            running = "RUNNING" in result.stdout if installed else False

        elif system == "Linux":
            # Check systemd service
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "async-crud-mcp"],
                capture_output=True,
                text=True
            )
            running = result.returncode == 0
            installed = running or "inactive" in result.stdout.lower()

        elif system == "Darwin":
            # Check launchd service
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True
            )
            installed = "async-crud-mcp" in result.stdout.lower()
            running = installed  # Simplified check

        else:
            print_status("Daemon Service", 'fail', f"Unknown platform: {system}")
            return 'fail'

        if installed:
            msg = "running" if running else "installed (not running)"
            status = 'pass' if running else 'fail'
            print_status("Daemon Service", status, msg)
        else:
            print_status("Daemon Service", 'fail', "Not installed")
            status = 'fail'

        return status

    except Exception as e:
        print_status("Daemon Service", 'fail', f"Check failed: {e}")
        return 'fail'


def get_logs_dir_fallback():
    """Get platform-appropriate logs directory (fallback when daemon.paths not available).

    Returns:
        Path to logs directory
    """
    system = platform.system()

    if system == "Windows":
        import os
        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            return Path(localappdata) / 'async-crud-mcp' / 'logs'
        return Path.home() / 'AppData' / 'Local' / 'async-crud-mcp' / 'logs'

    elif system == "Darwin":
        return Path.home() / 'Library' / 'Logs' / 'async-crud-mcp'

    else:  # Linux
        import os
        xdg_state_home = os.environ.get('XDG_STATE_HOME')
        if xdg_state_home:
            return Path(xdg_state_home) / 'async-crud-mcp' / 'logs'
        return Path.home() / '.local' / 'state' / 'async-crud-mcp' / 'logs'


def check_log_file_age(max_age_hours):
    """Check if log files exist and are recent.

    Args:
        max_age_hours: Maximum acceptable log file age in hours

    Returns:
        Status string: 'pass', 'fail', or 'skip'
    """
    print(f"\n{Colors.BOLD}Checking log file age...{Colors.RESET}")

    # Try to import get_logs_dir from daemon.paths, fall back if not available
    try:
        from async_crud_mcp.daemon.paths import get_logs_dir
        logs_dir = get_logs_dir()
    except ImportError:
        logs_dir = get_logs_dir_fallback()

    # Check if logs directory exists
    if not logs_dir.exists():
        print_status("Log File Age", 'fail', f"Logs directory not found: {logs_dir}")
        return 'fail'

    # Find log files (*.log and *.log.gz)
    log_patterns = [str(logs_dir / '*.log'), str(logs_dir / '*.log.gz')]
    log_files = []
    for pattern in log_patterns:
        log_files.extend(glob.glob(pattern))

    if not log_files:
        print_status("Log File Age", 'fail', f"No log files found in {logs_dir}")
        return 'fail'

    # Find newest log file
    newest_mtime = 0
    newest_file = None
    for log_file in log_files:
        mtime = Path(log_file).stat().st_mtime
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_file = log_file

    # Check age
    current_time = time.time()
    age_seconds = current_time - newest_mtime
    age_hours = age_seconds / 3600

    if age_hours > max_age_hours:
        print_status(
            "Log File Age",
            'fail',
            f"Newest log is {age_hours:.1f} hours old (max: {max_age_hours}h): {Path(newest_file).name}"
        )
        return 'fail'
    else:
        print_status(
            "Log File Age",
            'pass',
            f"Newest log is {age_hours:.1f} hours old (within {max_age_hours}h): {Path(newest_file).name}"
        )
        return 'pass'


def check_server_connectivity(port_override=None):
    """Check if SSE endpoint is accessible.

    Args:
        port_override: Optional port to use instead of config file port
    """
    print(f"\n{Colors.BOLD}Checking server connectivity...{Colors.RESET}")

    # Get host and port from config
    config_path = get_config_paths()

    host = "127.0.0.1"
    port = 8765

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            host = config.get("host", host)
            port = config.get("port", port)
        except Exception:
            pass

    # Override with CLI port if provided
    if port_override is not None:
        port = port_override

    # Try health check endpoint
    health_url = f"http://{host}:{port}/health"

    try:
        req = Request(health_url)
        req.add_header("User-Agent", "async-crud-mcp-test")

        with urlopen(req, timeout=5) as response:
            status = 'pass' if response.status == 200 else 'fail'

        print_status("Server Health", status, f"Connected to {health_url}")
        return status

    except URLError as e:
        print_status("Server Health", 'fail', f"Cannot connect to {health_url}: {e.reason}")
        return 'fail'
    except Exception as e:
        print_status("Server Health", 'fail', f"Connection error: {e}")
        return 'fail'


def main():
    """Main entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Post-install verification for async-crud-mcp',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Custom port for server connectivity check (overrides config file)'
    )
    parser.add_argument(
        '--skip-logs',
        action='store_true',
        help='Skip log file age check'
    )
    parser.add_argument(
        '--log-age',
        type=int,
        default=168,
        metavar='HOURS',
        help='Maximum acceptable log file age in hours (default: 168 = 7 days)'
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print(f"{Colors.BOLD}async-crud-mcp Post-Install Verification{Colors.RESET}")
    print("="*60)

    results = []

    # Run all checks
    results.append(("Python Version", check_python_version()))
    results.append(("Package Import", check_package_import()))
    results.append(("Configuration", check_config_file()))
    results.append(("Daemon Service", check_daemon_service()))
    results.append(("Server Connectivity", check_server_connectivity(port_override=args.port)))

    # Log file age check (conditional)
    if args.skip_logs:
        print(f"\n{Colors.BOLD}Checking log file age...{Colors.RESET}")
        print_status("Log File Age", 'skip', "Skipped (--skip-logs)")
        results.append(("Log File Age", 'skip'))
    else:
        results.append(("Log File Age", check_log_file_age(args.log_age)))

    # Summary
    print("\n" + "="*60)
    print(f"{Colors.BOLD}Summary{Colors.RESET}")
    print("="*60)

    passed_count = sum(1 for _, status in results if status == 'pass')
    failed_count = sum(1 for _, status in results if status == 'fail')
    skipped_count = sum(1 for _, status in results if status == 'skip')
    total_count = len(results)

    for name, status in results:
        if status == 'pass':
            status_str = f"{Colors.GREEN}PASS{Colors.RESET}"
        elif status == 'skip':
            status_str = f"{Colors.YELLOW}SKIP{Colors.RESET}"
        else:
            status_str = f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"  {status_str}  {name}")

    print("="*60)
    print(f"\nResults: {passed_count} passed, {failed_count} failed, {skipped_count} skipped out of {total_count} checks")

    # Overall verdict
    if failed_count == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}OVERALL: PASS{Colors.RESET}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}OVERALL: FAIL{Colors.RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
