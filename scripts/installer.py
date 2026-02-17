#!/usr/bin/env python3
"""async-crud-mcp Installer - stdlib-only interactive installer."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_CANCELLED = 130


def check_privileges():
    """Check if running with admin privileges on Windows (no-op on Unix)."""
    system = platform.system()

    if system == "Windows":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        # On Unix, user-level services (systemd --user / launchd) don't need root
        return True


def run_preflight_checks(target_dir):
    """Run preflight checks before installation.

    Returns:
        list: List of (check_name, passed, message) tuples
    """
    checks = []

    # Check 1: Python version >= 3.10
    py_version = sys.version_info
    if py_version >= (3, 10):
        checks.append(("Python version", True, f"Python {py_version.major}.{py_version.minor} (>= 3.10)"))
    else:
        checks.append(("Python version", False, f"Python {py_version.major}.{py_version.minor} (need >= 3.10)"))

    # Check 2: Disk space >= 500MB free
    try:
        usage = shutil.disk_usage(target_dir.parent if target_dir.exists() else target_dir.parent.parent)
        free_mb = usage.free / (1024 * 1024)
        if free_mb >= 500:
            checks.append(("Disk space", True, f"{free_mb:.0f} MB free (>= 500 MB)"))
        else:
            checks.append(("Disk space", False, f"{free_mb:.0f} MB free (need >= 500 MB)"))
    except Exception as e:
        checks.append(("Disk space", False, f"Could not check: {e}"))

    # Check 3: Write permissions to target directory
    try:
        test_dir = target_dir / ".installer-test"
        test_dir.mkdir(parents=True, exist_ok=True)
        if os.access(test_dir, os.W_OK):
            checks.append(("Write permissions", True, f"Can write to {target_dir}"))
            test_dir.rmdir()
        else:
            checks.append(("Write permissions", False, f"Cannot write to {target_dir}"))
    except Exception as e:
        checks.append(("Write permissions", False, f"Permission check failed: {e}"))

    return checks


def get_platform_paths():
    """Get platform-specific paths for installation (stdlib-only reimplementation)."""
    system = platform.system()

    if system == "Windows":
        appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        base_dir = Path(appdata) / "async-crud-mcp"
        config_dir = base_dir / "config"
        log_dir = base_dir / "logs"
    elif system == "Darwin":  # macOS
        base_dir = Path.home() / "Library" / "Application Support" / "async-crud-mcp"
        config_dir = base_dir / "config"
        log_dir = base_dir / "logs"
    else:  # Linux and others
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
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


def bootstrap_uv():
    """Bootstrap uv package manager (delegates to bootstrap_uv.py)."""
    print("[BOOTSTRAP] Installing uv package manager...")
    script_dir = Path(__file__).parent
    bootstrap_script = script_dir / "bootstrap_uv.py"

    try:
        result = subprocess.run(
            [sys.executable, str(bootstrap_script)],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to bootstrap uv: {e.stderr}", file=sys.stderr)
        return False


def create_venv(venv_dir):
    """Create virtual environment using uv with managed Python."""
    print(f"[VENV] Creating virtual environment at {venv_dir}...")

    try:
        subprocess.run(
            ["uv", "venv", str(venv_dir), "--managed-python"],
            check=True,
            capture_output=True,
            text=True
        )
        print("[OK] Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to create venv: {e.stderr}", file=sys.stderr)
        return False


def install_package(venv_dir):
    """Install async-crud-mcp package into venv."""
    print("[INSTALL] Installing async-crud-mcp package...")

    # Get the project root (parent of scripts/)
    project_root = Path(__file__).parent.parent

    # Determine python path in venv
    system = platform.system()
    if system == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"

    try:
        # Use uv pip install (uv-created venvs don't include pip)
        subprocess.run(
            ["uv", "pip", "install", "-e", str(project_root),
             "--python", str(python_path)],
            check=True,
            capture_output=True,
            text=True
        )
        print("[OK] Package installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install package: {e.stderr}", file=sys.stderr)
        return False


def configure_pywin32_dlls(venv_dir):
    """Configure pywin32 DLLs for Windows Service (Windows only).

    Copies pywintypes*.dll, pythoncom*.dll, and pythonservice.exe to venv root
    where pythonservice.exe expects to find them.
    """
    system = platform.system()
    if system != "Windows":
        return True

    print("[PYWIN32] Configuring pywin32 DLLs for Windows Service...")

    try:
        # Find pywin32_system32 directory
        site_packages = venv_dir / "Lib" / "site-packages"
        pywin32_system32 = site_packages / "pywin32_system32"
        pywin32_win32 = site_packages / "win32"

        if not pywin32_system32.exists():
            print("[WARN] pywin32_system32 directory not found, skipping DLL configuration")
            return True

        # Copy DLLs to venv root
        for dll_pattern in ["pywintypes*.dll", "pythoncom*.dll"]:
            for dll_file in pywin32_system32.glob(dll_pattern):
                dest = venv_dir / dll_file.name
                shutil.copy2(dll_file, dest)
                print(f"[OK] Copied {dll_file.name} to {dest}")

        # Copy pythonservice.exe if it exists
        if pywin32_win32.exists():
            pythonservice_exe = pywin32_win32 / "pythonservice.exe"
            if pythonservice_exe.exists():
                dest = venv_dir / "pythonservice.exe"
                shutil.copy2(pythonservice_exe, dest)
                print(f"[OK] Copied pythonservice.exe to {dest}")

        print("[OK] pywin32 DLLs configured")
        return True
    except Exception as e:
        print(f"[WARN] Failed to configure pywin32 DLLs: {e}")
        return False


def init_config(config_dir, config_file, port=None):
    """Initialize configuration files.

    Args:
        config_dir: Configuration directory path
        config_file: Configuration file path
        port: Optional port override (default: 8765)
    """
    print(f"[CONFIG] Initializing configuration at {config_file}...")

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    # Default configuration
    default_config = {
        "host": "127.0.0.1",
        "port": port if port is not None else 8765,
        "log_level": "INFO",
        "storage": {
            "data_dir": str(config_dir / "data")
        }
    }

    # Write config file if it doesn't exist
    if not config_file.exists():
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        print(f"[OK] Configuration created at {config_file}")
    else:
        print(f"[INFO] Configuration already exists at {config_file}")

    return True


def install_service():
    """Install platform service (systemd/launchd/Windows Service)."""
    print("[SERVICE] Installing platform service...")

    system = platform.system()
    script_dir = Path(__file__).parent.parent / "src" / "async_crud_mcp" / "daemon"

    if system == "Linux":
        installer_script = script_dir / "linux" / "systemd_installer.sh"
    elif system == "Darwin":
        installer_script = script_dir / "macos" / "launchd_installer.sh"
    elif system == "Windows":
        installer_script = script_dir / "windows" / "service_installer.bat"
    else:
        print(f"[WARN] Platform service not supported on {system}", file=sys.stderr)
        return False

    if not installer_script.exists():
        print(f"[WARN] Service installer not found: {installer_script}", file=sys.stderr)
        return False

    try:
        if system == "Windows":
            subprocess.run([str(installer_script), "install"], check=True)
        else:
            subprocess.run(["bash", str(installer_script), "install"], check=True)
        print("[OK] Service installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install service: {e}", file=sys.stderr)
        return False


def do_install(force=False, port=None):
    """Perform full installation.

    Args:
        force: Force reinstall (overwrite existing config/venv)
        port: Optional port override for configuration
    """
    print("\n" + "="*60)
    print("async-crud-mcp Installation")
    print("="*60 + "\n")

    # Get platform paths
    paths = get_platform_paths()

    # Step 0a: Check privileges (Windows only)
    if not check_privileges():
        print("[ERROR] Administrator privileges required on Windows", file=sys.stderr)
        print("        Please run this script as Administrator", file=sys.stderr)
        return EXIT_FAILED

    # Step 0b: Run preflight checks
    print("[PREFLIGHT] Running preflight checks...")
    preflight_results = run_preflight_checks(paths["base_dir"])

    # Print results
    print("\nPreflight Check Results:")
    print("-" * 60)
    for check_name, passed, message in preflight_results:
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {check_name}: {message}")
    print("-" * 60 + "\n")

    # Abort if any check failed
    if not all(passed for _, passed, _ in preflight_results):
        print("[ERROR] Preflight checks failed, aborting installation", file=sys.stderr)
        return EXIT_FAILED

    # Handle force flag
    if force:
        print("[FORCE] Force reinstall enabled - will overwrite existing installation")
        if paths["venv_dir"].exists():
            print(f"[FORCE] Removing existing venv at {paths['venv_dir']}")
            shutil.rmtree(paths["venv_dir"])
        if paths["config_file"].exists():
            print(f"[FORCE] Removing existing config at {paths['config_file']}")
            paths["config_file"].unlink()

    # Step 1: Bootstrap uv
    if not bootstrap_uv():
        return EXIT_FAILED

    # Step 2: Create venv
    if not create_venv(paths["venv_dir"]):
        return EXIT_FAILED

    # Step 3: Install package
    if not install_package(paths["venv_dir"]):
        return EXIT_FAILED

    # Step 3.5: Configure pywin32 DLLs (Windows only)
    if not configure_pywin32_dlls(paths["venv_dir"]):
        print("[WARN] pywin32 DLL configuration failed, service may not work")

    # Step 4: Initialize config
    if not init_config(paths["config_dir"], paths["config_file"], port=port):
        return EXIT_FAILED

    # Step 5: Install service
    if not install_service():
        print("[WARN] Service installation failed, but package is installed")

    # Step 6: Configure Claude Desktop
    print("\n[CONFIGURE] Configuring Claude Desktop integration...")
    configure_result = do_configure()
    if configure_result != EXIT_SUCCESS:
        print("[WARN] Claude Desktop configuration failed, but package is installed")
        print("       You can run 'python installer.py configure' later to retry")

    print("\n" + "="*60)
    print("[SUCCESS] Installation complete!")
    print("="*60)
    print(f"Installation directory: {paths['base_dir']}")
    print(f"Configuration file: {paths['config_file']}")
    print(f"Virtual environment: {paths['venv_dir']}")
    if port:
        print(f"Port: {port}")
    print("\nNext steps:")
    print("  1. Review configuration in config.json")
    print("  2. Start the daemon service")
    print("  3. Restart Claude Desktop for MCP integration")
    print("="*60 + "\n")

    return EXIT_SUCCESS


def do_uninstall(remove_all=False):
    """Delegate to uninstaller.py.

    Args:
        remove_all: Remove all files without confirmation prompts
    """
    print("[UNINSTALL] Delegating to uninstaller...")
    script_dir = Path(__file__).parent
    uninstaller_script = script_dir / "uninstaller.py"

    cmd = [sys.executable, str(uninstaller_script)]
    if remove_all:
        cmd.append("--all")

    try:
        subprocess.run(cmd, check=True)
        return EXIT_SUCCESS
    except subprocess.CalledProcessError:
        return EXIT_FAILED


def do_configure():
    """Run Claude Code configuration."""
    print("[CONFIGURE] Setting up Claude Desktop MCP configuration...")
    script_dir = Path(__file__).parent
    config_script = script_dir / "configure_claude_code.py"

    try:
        subprocess.run([sys.executable, str(config_script)], check=True)
        return EXIT_SUCCESS
    except subprocess.CalledProcessError:
        return EXIT_FAILED


def do_test():
    """Run post-install verification."""
    print("[TEST] Running post-install verification...")
    script_dir = Path(__file__).parent
    test_script = script_dir / "test_server.py"

    try:
        subprocess.run([sys.executable, str(test_script)], check=True)
        return EXIT_SUCCESS
    except subprocess.CalledProcessError:
        return EXIT_FAILED


def stop_service():
    """Stop the running platform service (Windows/Linux/macOS)."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["sc", "stop", "AsyncCrudMCP"],
                capture_output=True,
                text=True
            )
        elif system == "Linux":
            subprocess.run(
                ["systemctl", "--user", "stop", "async-crud-mcp"],
                capture_output=True,
                text=True
            )
        elif system == "Darwin":
            subprocess.run(
                ["launchctl", "unload",
                 str(Path.home() / "Library" / "LaunchAgents" / "com.async-crud-mcp.daemon.plist")],
                capture_output=True,
                text=True
            )
    except Exception:
        pass


def do_reinstall():
    """Stop existing service and perform a fresh install."""
    print("[REINSTALL] Stopping existing service...")
    stop_service()
    return do_install(force=True)


def show_menu():
    """Show interactive menu and handle user selection."""
    try:
        while True:
            print("\n" + "="*60)
            print("async-crud-mcp Installer Menu")
            print("="*60)
            print("1. Install async-crud-mcp")
            print("2. Reinstall async-crud-mcp")
            print("3. Uninstall async-crud-mcp")
            print("4. Quit")
            print("="*60)

            try:
                choice = input("\nSelect an option (1-4): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[INFO] Cancelled by user")
                return EXIT_CANCELLED

            if choice == "1":
                exit_code = do_install()
                if exit_code != EXIT_SUCCESS:
                    print("\n[ERROR] Installation failed", file=sys.stderr)
            elif choice == "2":
                exit_code = do_reinstall()
                if exit_code != EXIT_SUCCESS:
                    print("\n[ERROR] Reinstall failed", file=sys.stderr)
            elif choice == "3":
                exit_code = do_uninstall()
                if exit_code != EXIT_SUCCESS:
                    print("\n[ERROR] Uninstall failed", file=sys.stderr)
            elif choice == "4":
                print("\n[INFO] Quitting")
                return EXIT_SUCCESS
            else:
                print("\n[ERROR] Invalid choice. Please enter 1-4.", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user")
        return EXIT_CANCELLED


def main():
    """Main entry point with CLI parsing."""
    parser = argparse.ArgumentParser(
        description="async-crud-mcp installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python installer.py                      # Show interactive menu
  python installer.py install              # Run installation (includes Claude Desktop config)
  python installer.py install --force      # Force reinstall
  python installer.py install --port 9000  # Install with custom port
  python installer.py uninstall            # Run uninstallation
  python installer.py uninstall --all      # Remove all files without prompts
  python installer.py configure            # Configure Claude Desktop (standalone)
  python installer.py test                 # Test installation
"""
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["install", "uninstall", "configure", "test", "menu"],
        default="menu",
        help="Command to execute (default: menu)"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force reinstall (overwrite existing config/venv) - install only"
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Override default port (8765) - install only"
    )

    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Remove all files without confirmation - uninstall only"
    )

    args = parser.parse_args()

    try:
        # Execute command
        if args.command == "install":
            return do_install(force=args.force, port=args.port)
        elif args.command == "uninstall":
            return do_uninstall(remove_all=args.all)
        elif args.command == "configure":
            return do_configure()
        elif args.command == "test":
            return do_test()
        else:  # menu
            return show_menu()
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user")
        return EXIT_CANCELLED
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return EXIT_FAILED


if __name__ == "__main__":
    exit_code = main()
    if exit_code != EXIT_SUCCESS:
        input("\nPress Enter to exit...")
    sys.exit(exit_code)
