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


def get_venv_python():
    """Get the venv Python executable path.

    Returns:
        Path to venv python.exe (Windows) or python (Unix), or None if not found
    """
    import os
    system = platform.system()

    if system == "Windows":
        appdata = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        venv_python = Path(appdata) / "async-crud-mcp" / "venv" / "Scripts" / "python.exe"
    elif system == "Darwin":
        venv_python = Path.home() / "Library" / "Application Support" / "async-crud-mcp" / "venv" / "bin" / "python"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        venv_python = Path(xdg_data_home) / "async-crud-mcp" / "venv" / "bin" / "python"

    return venv_python if venv_python.exists() else None


def check_package_import():
    """Check if async-crud-mcp package can be imported (via venv Python)."""
    print(f"\n{Colors.BOLD}Checking package installation...{Colors.RESET}")

    venv_python = get_venv_python()
    if venv_python is None:
        print_status("Package Import", 'fail', "Venv Python not found")
        return 'fail'

    try:
        result = subprocess.run(
            [str(venv_python), "-c",
             "import async_crud_mcp; print(getattr(async_crud_mcp, '__version__', 'unknown'))"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print_status("Package Import", 'pass', f"async-crud-mcp version {version}")
            return 'pass'
        else:
            print_status("Package Import", 'fail', f"Import failed: {result.stderr.strip()}")
            return 'fail'
    except subprocess.TimeoutExpired:
        print_status("Package Import", 'fail', "Import check timed out")
        return 'fail'
    except Exception as e:
        print_status("Package Import", 'fail', f"Import check error: {e}")
        return 'fail'


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

        daemon_config = config.get("daemon", {})
        host = daemon_config.get("host", "N/A")
        port = daemon_config.get("port", "N/A")

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
                ["sc", "query", "async-crud-mcp-daemon"],
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

    On Windows the dispatcher writes logs under ProgramData (system-wide service),
    while per-user logs go under LOCALAPPDATA. Check both locations.

    Returns:
        Path to logs directory
    """
    system = platform.system()

    if system == "Windows":
        import os
        # ProgramData is primary location for dispatcher logs (system service)
        programdata = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
        pd_logs = Path(programdata) / 'async-crud-mcp' / 'logs'
        if pd_logs.exists():
            return pd_logs
        # Fallback to LOCALAPPDATA (per-user)
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

    Searches all 3 log tiers:
    - User: LOCALAPPDATA/async-crud-mcp/logs/ (server.log, audit.log)
    - System: ProgramData/async-crud-mcp/logs/ (dispatcher.log, audit.log)
    - Fallback: get_logs_dir_fallback() for non-standard layouts

    Args:
        max_age_hours: Maximum acceptable log file age in hours

    Returns:
        Status string: 'pass', 'fail', or 'skip'
    """
    print(f"\n{Colors.BOLD}Checking log file age...{Colors.RESET}")

    # Collect candidate directories from all tiers
    candidate_dirs = []

    # Tier 2: User-level logs
    try:
        from async_crud_mcp.daemon.paths import get_logs_dir
        candidate_dirs.append(get_logs_dir())
    except ImportError:
        pass

    # Tier 3: System-level logs
    try:
        from async_crud_mcp.daemon.paths import get_shared_dir
        candidate_dirs.append(get_shared_dir() / "logs")
    except ImportError:
        pass

    # Fallback (probes ProgramData then LOCALAPPDATA)
    candidate_dirs.append(get_logs_dir_fallback())

    # Deduplicate while preserving order
    seen = set()
    unique_dirs = []
    for d in candidate_dirs:
        resolved = d.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_dirs.append(d)

    # Search for log files across all candidate directories
    log_files = []
    for logs_dir in unique_dirs:
        if not logs_dir.exists():
            continue
        for pattern in [str(logs_dir / '**' / '*.log'), str(logs_dir / '**' / '*.log.gz')]:
            log_files.extend(glob.glob(pattern, recursive=True))

    if not log_files:
        dirs_str = ", ".join(str(d) for d in unique_dirs)
        print_status("Log File Age", 'fail', f"No log files found in: {dirs_str}")
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
    port = 8720

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            daemon_config = config.get("daemon", {})
            host = daemon_config.get("host", host)
            port = daemon_config.get("port", port)
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
        '--retries',
        type=int,
        default=0,
        metavar='N',
        help='Number of retries for server connectivity check (default: 0)'
    )
    parser.add_argument(
        '--retry-delay',
        type=int,
        default=3,
        metavar='SECONDS',
        help='Delay between retries in seconds (default: 3)'
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
    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='Skip interactive "Press Enter to close" prompt (used by installer)'
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
    # Server connectivity with retry support
    connectivity_status = check_server_connectivity(port_override=args.port)
    if connectivity_status == 'fail' and args.retries > 0:
        for attempt in range(1, args.retries + 1):
            print(f"\n{Colors.YELLOW}Retrying connectivity check ({attempt}/{args.retries}) "
                  f"in {args.retry_delay}s...{Colors.RESET}")
            time.sleep(args.retry_delay)
            connectivity_status = check_server_connectivity(port_override=args.port)
            if connectivity_status != 'fail':
                break
    results.append(("Server Connectivity", connectivity_status))

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
        exit_code = 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}OVERALL: FAIL{Colors.RESET}\n")
        exit_code = 1

    # Interactive prompt so the window stays open when double-clicked
    if sys.stdin.isatty() and not args.no_prompt:
        try:
            input("Press Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
