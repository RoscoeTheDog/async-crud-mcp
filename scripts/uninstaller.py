#!/usr/bin/env python3
"""async-crud-mcp Uninstaller - stdlib-only cleanup script."""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Script directory for locating sibling scripts
_SCRIPT_DIR = Path(__file__).parent


def get_platform_paths():
    """Get platform-specific paths for uninstallation (matches installer.py)."""
    system = platform.system()

    if system == "Windows":
        import os
        appdata = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        base_dir = Path(appdata) / "async-crud-mcp"
        config_dir = base_dir / "config"
        log_dir = base_dir / "logs"
    elif system == "Darwin":  # macOS
        base_dir = Path.home() / "Library" / "Application Support" / "async-crud-mcp"
        config_dir = base_dir / "config"
        log_dir = base_dir / "logs"
    else:  # Linux and others
        import os
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        xdg_data_home = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        config_dir = Path(xdg_config_home) / "async-crud-mcp"
        log_dir = Path(xdg_data_home) / "async-crud-mcp" / "logs"
        base_dir = config_dir.parent

    venv_dir = base_dir / "venv"

    return {
        "base_dir": base_dir,
        "config_dir": config_dir,
        "log_dir": log_dir,
        "venv_dir": venv_dir,
        "config_file": config_dir / "config.json",
    }


def stop_daemon():
    """Stop running daemon service."""
    print("[STOP] Stopping daemon service...")

    system = platform.system()

    try:
        if system == "Windows":
            # Stop Windows service
            subprocess.run(
                ["sc", "stop", "AsyncCrudMCP"],
                capture_output=True,
                text=True
            )
        elif system == "Linux":
            # Stop systemd service
            subprocess.run(
                ["systemctl", "--user", "stop", "async-crud-mcp"],
                capture_output=True,
                text=True
            )
        elif system == "Darwin":
            # Stop launchd service
            subprocess.run(
                ["launchctl", "unload", str(Path.home() / "Library" / "LaunchAgents" / "com.async-crud-mcp.plist")],
                capture_output=True,
                text=True
            )

        print("[OK] Daemon stopped (or was not running)")
        return True
    except Exception as e:
        print(f"[WARN] Could not stop daemon: {e}")
        return False


def uninstall_service(venv_dir):
    """Uninstall platform service using the daemon installer API.

    Args:
        venv_dir: Path to the virtual environment directory
    """
    print("[SERVICE] Uninstalling platform service...")

    system = platform.system()
    if system == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"

    if not python_path.exists():
        print(f"[WARN] Venv Python not found at {python_path}, skipping service uninstall")
        return False

    try:
        subprocess.run(
            [str(python_path), "-c",
             "from async_crud_mcp.daemon.installer import get_installer; get_installer().uninstall()"],
            check=True,
            capture_output=True,
            text=True
        )
        print("[OK] Service uninstalled")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Failed to uninstall service: {e.stderr}")
        return False


def remove_venv(venv_dir):
    """Remove virtual environment directory."""
    if not venv_dir.exists():
        print(f"[INFO] Virtual environment not found at {venv_dir}")
        return True

    print(f"[REMOVE] Removing virtual environment at {venv_dir}...")
    try:
        shutil.rmtree(venv_dir)
        print("[OK] Virtual environment removed")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to remove venv: {e}", file=sys.stderr)
        return False


def remove_config(config_dir, skip_confirm=False):
    """Remove configuration files."""
    if not config_dir.exists():
        print(f"[INFO] Configuration directory not found at {config_dir}")
        return True

    if not skip_confirm:
        response = input(f"Remove configuration directory {config_dir}? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            print("[INFO] Keeping configuration files")
            return True

    print(f"[REMOVE] Removing configuration at {config_dir}...")
    try:
        shutil.rmtree(config_dir)
        print("[OK] Configuration removed")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to remove config: {e}", file=sys.stderr)
        return False


def remove_logs(log_dir, skip_confirm=False):
    """Remove log files."""
    if not log_dir.exists():
        print(f"[INFO] Log directory not found at {log_dir}")
        return True

    if not skip_confirm:
        response = input(f"Remove log directory {log_dir}? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            print("[INFO] Keeping log files")
            return True

    print(f"[REMOVE] Removing logs at {log_dir}...")
    try:
        shutil.rmtree(log_dir)
        print("[OK] Logs removed")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to remove logs: {e}", file=sys.stderr)
        return False


def remove_base_dir(base_dir, skip_confirm=False):
    """Remove base installation directory."""
    if not base_dir.exists():
        print(f"[INFO] Base directory not found at {base_dir}")
        return True

    if not skip_confirm:
        response = input(f"Remove entire installation directory {base_dir}? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            print("[INFO] Keeping installation directory")
            return True

    print(f"[REMOVE] Removing installation directory at {base_dir}...")
    try:
        shutil.rmtree(base_dir)
        print("[OK] Installation directory removed")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to remove base directory: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point with CLI parsing."""
    parser = argparse.ArgumentParser(
        description="async-crud-mcp uninstaller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python uninstaller.py                 # Interactive uninstallation
  python uninstaller.py --yes           # Skip all confirmations
  python uninstaller.py --all           # Remove everything without prompts
  python uninstaller.py --keep-config   # Keep configuration files
"""
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip all confirmation prompts"
    )

    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Remove all files without confirmation (equivalent to --yes + remove base dir)"
    )

    parser.add_argument(
        "--keep-config",
        action="store_true",
        help="Keep configuration files"
    )

    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Keep log files"
    )

    args = parser.parse_args()

    # --all implies --yes and removes everything
    if args.all:
        args.yes = True

    print("\n" + "="*60)
    print("async-crud-mcp Uninstallation")
    print("="*60 + "\n")

    # Get platform paths
    paths = get_platform_paths()

    # Step 1: Stop daemon
    stop_daemon()

    # Step 2: Uninstall service
    uninstall_service(paths["venv_dir"])

    # Step 2.5: Remove from Claude Code CLI and Desktop configs
    config_script = _SCRIPT_DIR / "configure_claude_code.py"
    if config_script.exists():
        subprocess.run(
            [sys.executable, str(config_script), "--remove"], check=False
        )
        subprocess.run(
            [sys.executable, str(config_script), "--remove", "--desktop"],
            check=False,
        )

    # Step 3: Remove venv
    remove_venv(paths["venv_dir"])

    # Step 4: Remove config (optional)
    if args.all or not args.keep_config:
        remove_config(paths["config_dir"], skip_confirm=args.yes)

    # Step 5: Remove logs (optional)
    if args.all or not args.keep_logs:
        remove_logs(paths["log_dir"], skip_confirm=args.yes)

    # Step 6: Remove base directory (optional)
    if args.all or args.yes:
        remove_base_dir(paths["base_dir"], skip_confirm=True)

    print("\n" + "="*60)
    print("[SUCCESS] Uninstallation complete!")
    print("="*60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
