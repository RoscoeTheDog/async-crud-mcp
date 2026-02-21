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


# ============================================================
# Console Output (ANSI colors for terminals)
# ============================================================


class Colors:
    """ANSI color codes (disabled on Windows without ANSI support)."""

    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    @classmethod
    def init(cls):
        """Enable ANSI colors on Windows 10+."""
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                cls.RESET = cls.RED = cls.GREEN = cls.YELLOW = ""
                cls.BOLD = cls.DIM = ""


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

    # Check 4: Git Bash available (Windows only, required for shell extension)
    if sys.platform == "win32":
        bash_path = _find_git_bash()
        if bash_path:
            checks.append(("Git Bash", True, f"Found at {bash_path}"))
        else:
            checks.append((
                "Git Bash", False,
                "Not found. Install Git for Windows: https://git-scm.com/downloads/win"
            ))

    return checks


def _find_git_bash():
    """Find Git Bash on Windows for shell extension support.

    Returns:
        Path to bash.exe if found, None otherwise.
    """
    # 1. Env var
    env_path = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. bash on PATH
    bash_on_path = shutil.which("bash")
    if bash_on_path:
        return bash_on_path

    # 3. Derive from git
    git_path = shutil.which("git")
    if git_path:
        git_dir = Path(git_path).resolve().parent
        for candidate in (
            git_dir.parent / "bin" / "bash.exe",
            git_dir / "bash.exe",
        ):
            if candidate.is_file():
                return str(candidate)

    # 4. Known paths
    for known in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.isfile(known):
            return known

    return None


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
        # CRITICAL (ADR-015 C1): Do NOT use -e (editable). Editable installs
        # add the developer's source directory to sys.path. LocalSystem cannot
        # access C:\Users\<developer>\... and the service fails to import.
        subprocess.run(
            ["uv", "pip", "install", str(project_root),
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


def _get_base_python_dir(venv_dir):
    """Find the base Python directory from the venv's pyvenv.cfg.

    The 'home' key in pyvenv.cfg points to the directory containing
    the base Python interpreter (e.g., uv-managed Python location).
    """
    pyvenv_cfg = venv_dir / "pyvenv.cfg"
    if not pyvenv_cfg.exists():
        return None
    try:
        for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("home"):
                _, _, value = line.partition("=")
                home_dir = Path(value.strip())
                if home_dir.exists():
                    return home_dir
    except Exception:
        pass
    return None


def configure_pywin32_dlls(venv_dir):
    """Configure pywin32 DLLs for Windows Service (Windows only).

    Copies pywintypes*.dll, pythoncom*.dll, pythonservice.exe, and core
    Python DLLs (python3.dll, python3XX.dll) to venv root where
    pythonservice.exe expects to find them.
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

        # Copy core Python DLLs (python3.dll, python312.dll, etc.) to venv root.
        # pythonservice.exe needs these at load time but uv-managed Python
        # stores them outside the venv (in %APPDATA%\uv\python\...).
        base_python_dir = _get_base_python_dir(venv_dir)
        if base_python_dir:
            for dll_file in base_python_dir.glob("python3*.dll"):
                dest = venv_dir / dll_file.name
                if not dest.exists():
                    shutil.copy2(dll_file, dest)
                    print(f"[OK] Copied {dll_file.name} to {dest}")
            # Copy vcruntime DLLs if present (needed by python3XX.dll itself)
            for vcrt_name in ["vcruntime140.dll", "vcruntime140_1.dll"]:
                vcrt_file = base_python_dir / vcrt_name
                if vcrt_file.exists():
                    dest = venv_dir / vcrt_name
                    if not dest.exists():
                        shutil.copy2(vcrt_file, dest)
                        print(f"[OK] Copied {vcrt_name} to {dest}")
        else:
            print("[WARN] Could not find base Python directory, "
                  "core Python DLLs not copied")

        # Create pythonXY._pth so pythonservice.exe can find servicemanager.
        # pythonservice.exe embeds python3XX.dll but never processes .pth files
        # or pyvenv.cfg, so sys.path is missing win32/ and site-packages/.
        # A _pth file next to the DLL is Python's standard mechanism for
        # embedded interpreters to configure sys.path.
        _create_pth_file(venv_dir)

        print("[OK] pywin32 DLLs configured")
        return True
    except Exception as e:
        print(f"[WARN] Failed to configure pywin32 DLLs: {e}")
        return False


def _create_pth_file(venv_dir):
    """Create a pythonXY._pth file in the venv root for pythonservice.exe.

    When Py_Initialize() finds pythonXY._pth next to python3XX.dll, it uses
    its contents as the **complete** sys.path, replacing all default path
    computation. This means the file must include:
      - The base Python stdlib (Lib/, DLLs/, pythonXY.zip) so core modules
        like 'encodings' and 'os' are available
      - The venv's site-packages (for async_crud_mcp, loguru, etc.)
      - The win32 directories (for servicemanager, win32service, etc.)

    This file only affects executables that load python3XX.dll from the venv
    root (i.e., pythonservice.exe). Scripts/python.exe loads the DLL from
    the base Python location via pyvenv.cfg, so it is unaffected.

    Args:
        venv_dir: Path to the virtual environment root directory
    """
    # Find the versioned Python DLL (e.g., python312.dll), excluding python3.dll
    versioned_dlls = [
        p for p in venv_dir.glob("python3*.dll")
        if p.stem != "python3"
    ]
    if not versioned_dlls:
        print("[WARN] No versioned python3XX.dll found in venv root, "
              "skipping _pth file creation")
        return

    # Derive the _pth filename from the DLL name (python312.dll -> python312._pth)
    dll_name = versioned_dlls[0].stem  # e.g. "python312"
    pth_file = venv_dir / f"{dll_name}._pth"

    # The base Python directory contains the stdlib (Lib/, DLLs/, pythonXY.zip).
    # Without these, pythonservice.exe cannot even initialize (no 'encodings').
    base_python_dir = _get_base_python_dir(venv_dir)

    lines = []

    # Base Python stdlib paths (absolute - they live outside the venv)
    if base_python_dir:
        zip_file = base_python_dir / f"{dll_name}.zip"
        if zip_file.exists():
            lines.append(str(zip_file))
        stdlib_dir = base_python_dir / "Lib"
        if stdlib_dir.exists():
            lines.append(str(stdlib_dir))
        dlls_dir = base_python_dir / "DLLs"
        if dlls_dir.exists():
            lines.append(str(dlls_dir))
    else:
        print("[WARN] Could not find base Python directory; "
              "_pth file may be incomplete (missing stdlib)")

    # Venv-local paths (relative to the venv root where the _pth file lives)
    lines.append(".")
    lines.append("Lib\\site-packages")
    lines.append("Lib\\site-packages\\win32")
    lines.append("Lib\\site-packages\\win32\\lib")
    lines.append("Lib\\site-packages\\Pythonwin")
    lines.append("import site")

    pth_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Created {pth_file.name} for pythonservice.exe sys.path")


def verify_package_import(venv_dir):
    """Verify the package can be imported using the venv's Python (ADR-015 C5).

    This catches issues where the installer's Python can import the package
    but the venv's Python cannot (e.g., missing dependencies, wrong sys.path).

    Args:
        venv_dir: Path to the virtual environment directory

    Returns:
        True if import succeeds, False otherwise
    """
    print("[VERIFY] Running post-install import verification (ADR-015 C5)...")

    system = platform.system()
    if system == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"

    try:
        result = subprocess.run(
            [str(python_path), "-c", "import async_crud_mcp"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print("[OK] Package import verified")
            return True
        else:
            print(f"[ERROR] Import verification failed: {result.stderr}", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("[ERROR] Import verification timed out", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[ERROR] Import verification error: {e}", file=sys.stderr)
        return False


def init_config(config_dir, config_file, port=None):
    """Initialize configuration files.

    Args:
        config_dir: Configuration directory path
        config_file: Configuration file path
        port: Optional port override (default: 8720)
    """
    print(f"[CONFIG] Initializing configuration at {config_file}...")

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    # Default configuration (nested schema matching daemon's config_init)
    default_config = {
        "daemon": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": port if port is not None else 8720,
            "transport": "sse",
            "log_level": "INFO",
        },
        "server": {}
    }

    # Write config file if it doesn't exist
    if not config_file.exists():
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        print(f"[OK] Configuration created at {config_file}")
    else:
        print(f"[INFO] Configuration already exists at {config_file}")

    return True


def install_service(venv_dir):
    """Install platform service using the daemon installer API.

    Args:
        venv_dir: Path to the virtual environment directory
    """
    print("[SERVICE] Installing platform service...")

    system = platform.system()
    if system == "Windows":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"

    try:
        subprocess.run(
            [str(python_path), "-c",
             "from async_crud_mcp.daemon.installer import get_installer; get_installer().install()"],
            check=True,
            capture_output=True,
            text=True
        )
        print("[OK] Service installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Service installation failed: {e.stderr}", file=sys.stderr)
        return False


def start_service():
    """Start the platform service after installation.

    Returns:
        True if service started successfully, False otherwise
    """
    print("[SERVICE] Starting platform service...")

    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["sc", "start", "async-crud-mcp-daemon"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Service started")
                return True
            else:
                print(f"[WARN] Service start returned: {result.stderr.strip()}")
                return False
        elif system == "Linux":
            result = subprocess.run(
                ["systemctl", "--user", "start", "async-crud-mcp"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Service started")
                return True
            else:
                print(f"[WARN] Service start failed: {result.stderr.strip()}")
                return False
        elif system == "Darwin":
            plist_path = (Path.home() / "Library" / "LaunchAgents"
                          / "com.async-crud-mcp.daemon.plist")
            result = subprocess.run(
                ["launchctl", "load", str(plist_path)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Service started")
                return True
            else:
                print(f"[WARN] Service start failed: {result.stderr.strip()}")
                return False
        else:
            print(f"[WARN] Unsupported platform: {system}")
            return False
    except Exception as e:
        print(f"[WARN] Failed to start service: {e}")
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
            if not _robust_rmtree(paths["venv_dir"]):
                print("[FATAL] Cannot remove existing venv. A process may still be "
                      "locking files.", file=sys.stderr)
                print("        Close any terminals or editors using the venv and retry.",
                      file=sys.stderr)
                return EXIT_FAILED
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

    # Step 3.6: Post-install import verification (ADR-015 C5)
    if not verify_package_import(paths["venv_dir"]):
        print("[ERROR] Package installed but cannot be imported in the venv", file=sys.stderr)
        return EXIT_FAILED

    # Step 4: Initialize config
    if not init_config(paths["config_dir"], paths["config_file"], port=port):
        return EXIT_FAILED

    # Step 5: Install service
    if not install_service(paths["venv_dir"]):
        print("[WARN] Service installation failed, but package is installed")

    # Step 5.5: Start service
    if not start_service():
        print("[WARN] Service start failed. You can start it manually with:")
        print("       sc start async-crud-mcp-daemon")

    # Step 6: Configure Claude Code CLI + Desktop
    print("\n[CONFIGURE] Configuring Claude Code integration...")
    configure_result = do_configure()
    if configure_result != EXIT_SUCCESS:
        print("[WARN] Claude Code configuration failed, but package is installed")
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
    print("  2. Restart Claude Desktop for MCP integration")
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
    """Run Claude Code CLI + Desktop configuration."""
    script_dir = Path(__file__).parent
    config_script = script_dir / "configure_claude_code.py"

    # Primary: Claude Code CLI (~/.claude.json)
    print("[CONFIGURE] Setting up Claude Code CLI configuration...")
    try:
        subprocess.run([sys.executable, str(config_script)], check=True)
    except subprocess.CalledProcessError:
        return EXIT_FAILED

    # Secondary: Claude Desktop (best-effort)
    print("[CONFIGURE] Setting up Claude Desktop configuration...")
    subprocess.run([sys.executable, str(config_script), "--desktop"], check=False)

    return EXIT_SUCCESS


def do_test():
    """Run post-install verification."""
    print("[TEST] Running post-install verification...")
    script_dir = Path(__file__).parent
    test_script = script_dir / "test_server.py"

    try:
        subprocess.run([sys.executable, str(test_script), "--no-prompt"], check=True)
        return EXIT_SUCCESS
    except subprocess.CalledProcessError:
        return EXIT_FAILED


def _is_service_marked_for_deletion(service_name):
    """Check if a Windows service is stuck in marked-for-deletion state (ADR-017).

    The SCM sets DeleteFlag=1 in the registry when DeleteService() is called
    but open handles prevent finalization.

    Args:
        service_name: Windows service name to check

    Returns:
        True if service is marked for deletion, False otherwise
    """
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        key = winreg.OpenKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            f"SYSTEM\\CurrentControlSet\\Services\\{service_name}",
            0, winreg.KEY_READ
        )
        try:
            value, _ = winreg.QueryValueEx(key, "DeleteFlag")
            return value == 1
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except (FileNotFoundError, OSError):
        return False


def _find_running_processes(names):
    """Find which of the given process names are currently running (Windows).

    Args:
        names: Iterable of process executable names (e.g., "taskmgr.exe")

    Returns:
        List of (name, pid) tuples for running processes
    """
    found = []
    for name in names:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    if name.lower() in line.lower():
                        # CSV format: "name","pid","session","session#","mem"
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[1].strip('"'))
                                found.append((name, pid))
                            except ValueError:
                                found.append((name, 0))
        except (subprocess.TimeoutExpired, OSError):
            pass
    return found


def _kill_venv_python(venv_dir):
    """Kill any python.exe processes running from the given venv directory.

    On Windows, after stopping a service, child python.exe processes from
    the venv may linger and hold file locks preventing venv deletion.
    Uses PowerShell Get-CimInstance (works on Windows 10/11, no wmic dependency).
    """
    if platform.system() != "Windows":
        return
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
            "| Select-Object ProcessId,ExecutablePath "
            "| ForEach-Object { $_.ProcessId.ToString() + '|' + $_.ExecutablePath }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15
        )
        venv_lower = str(venv_dir).lower()
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            pid_str, exe_path = line.split("|", 1)
            if exe_path and venv_lower in exe_path.lower():
                try:
                    pid = int(pid_str)
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, text=True, timeout=10
                    )
                    print(f"[INFO] Killed venv python.exe (PID {pid})")
                except (ValueError, subprocess.TimeoutExpired, OSError):
                    pass
    except (subprocess.TimeoutExpired, OSError):
        pass


def _robust_rmtree(path, retries=3, delay=2):
    """Remove a directory tree with retry logic for Windows locked files.

    On Windows, file handles may take a moment to release after killing
    processes.  This retries with increasing delays and clears read-only
    flags on permission errors.
    """
    import time as _time
    import stat

    def _on_error(func, fpath, _exc_info):
        """Handle rmtree errors by clearing read-only and retrying."""
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except OSError:
            pass  # Will be retried at the outer level

    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_on_error)
            return True
        except (PermissionError, OSError) as exc:
            if attempt < retries - 1:
                wait = delay * (attempt + 1)
                print(f"[WARN] Removal blocked ({exc}), retrying in {wait}s...")
                _time.sleep(wait)
            else:
                print(f"[ERROR] Could not remove {path} after {retries} attempts: {exc}")
                return False
    return False


def _kill_process(name, pid=None):
    """Kill a process by name or PID (Windows).

    Args:
        name: Process executable name (for logging)
        pid: Optional specific PID to kill. If None, kills by image name.

    Returns:
        True if taskkill succeeded, False otherwise
    """
    try:
        if pid and pid > 0:
            cmd = ["taskkill", "/F", "/PID", str(pid)]
        else:
            cmd = ["taskkill", "/F", "/IM", name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ADR-017: Tiered process cleanup for service reinstallation
# Tier 1: Auto-kill (low risk, no user data)
_TIER1_PROCESSES = {
    "pythonservice.exe": "service binary (ours)",
    "mmc.exe": "Services console / Computer Management",
}

# Tier 2: Prompt user (may have active user state)
_TIER2_PROCESSES = {
    "taskmgr.exe": "Task Manager (Services tab holds service handles)",
    "procexp.exe": "Process Explorer (enumerates all services)",
    "procexp64.exe": "Process Explorer 64-bit (enumerates all services)",
    "perfmon.exe": "Performance Monitor (service performance counters)",
}


def kill_blocking_processes():
    """Kill or prompt to kill processes that prevent Windows service deletion.

    ADR-017: Tiered process cleanup strategy for error 1072.
    - Tier 1 (pythonservice.exe, mmc.exe): Auto-kill silently
    - Tier 2 (taskmgr, procexp, perfmon): Prompt user before killing
    - Tier 3 (AV, monitoring agents): Handled by retry loop in install_service()

    On non-Windows platforms this is a no-op.
    """
    if platform.system() != "Windows":
        return

    import time as _time

    # --- Tier 1: Auto-kill (safe, no user data at risk) ---
    for proc_name, description in _TIER1_PROCESSES.items():
        if _kill_process(proc_name):
            print(f"[INFO] Killed {proc_name} ({description})")

    _time.sleep(1)

    # Check if we're stuck in marked-for-deletion state
    service_name = "async-crud-mcp-daemon"
    if not _is_service_marked_for_deletion(service_name):
        return  # No stuck deletion, Tier 1 was sufficient

    # --- Tier 2: Prompt user for higher-risk processes ---
    running_tier2 = _find_running_processes(_TIER2_PROCESSES.keys())
    if not running_tier2:
        # No Tier 2 processes found -- must be Tier 3 (AV, monitoring, etc.)
        print("[WARN] Service is marked for deletion but no known handle holders found.")
        print("       An antivirus, monitoring agent, or other background process may")
        print("       be holding a handle. The installer will retry automatically.")
        return

    print("")
    print("[WARN] Service is marked for deletion but open handles are preventing removal.")
    print("[WARN] The following processes may be holding service handles:")
    print("")

    for proc_name, pid in running_tier2:
        description = _TIER2_PROCESSES.get(proc_name, "unknown")
        print(f"       {proc_name} (PID {pid}) - {description}")

    print("")

    for proc_name, pid in running_tier2:
        description = _TIER2_PROCESSES.get(proc_name, "unknown")
        try:
            answer = input(f"  Kill {proc_name} (PID {pid}) to continue? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n[INFO] Skipping -- will rely on retry loop")
            break

        if answer in ("", "y", "yes"):
            if _kill_process(proc_name, pid):
                print(f"  [OK] Killed {proc_name} (PID {pid})")
            else:
                print(f"  [WARN] Failed to kill {proc_name} (PID {pid})")
        else:
            print(f"  [INFO] Skipping {proc_name}")

    _time.sleep(2)


def stop_service():
    """Stop the running platform service (Windows/Linux/macOS)."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["sc", "stop", "async-crud-mcp-daemon"],
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
    import time
    time.sleep(2)  # Give Windows SCM time to process the stop
    print("[REINSTALL] Cleaning up blocking processes (ADR-017)...")
    kill_blocking_processes()
    paths = get_platform_paths()
    _kill_venv_python(paths["venv_dir"])
    time.sleep(1)  # Give OS time to release file handles after process kill
    return do_install(force=True)


def interactive_menu():
    """Display interactive menu and return user's choice.

    Returns:
        Tuple of (command_string, options_dict) where command is one of:
        "install", "reinstall", "uninstall", "test", or "quit".
    """
    Colors.init()

    print("\n" + "=" * 48)
    print("  async-crud-mcp Setup")
    print("=" * 48)
    print()
    print("  Select an action:")
    print()
    print(f"    {Colors.BOLD}1{Colors.RESET}) Install (fresh installation)")
    print(f"    {Colors.BOLD}2{Colors.RESET}) Reinstall (force recreate venv)")
    print(f"    {Colors.BOLD}3{Colors.RESET}) Uninstall")
    print(f"    {Colors.BOLD}4{Colors.RESET}) Test (verify server is running)")
    print(f"    {Colors.BOLD}5{Colors.RESET}) Quit")
    print()

    while True:
        try:
            choice = input("  Enter choice [1-5]: ").strip()
        except (KeyboardInterrupt, EOFError):
            return "quit", {}

        if choice == "1":
            return "install", {}
        elif choice == "2":
            return "reinstall", {}
        elif choice == "3":
            return "uninstall", {}
        elif choice == "4":
            return "test", {}
        elif choice == "5":
            return "quit", {}
        else:
            print(f"  {Colors.RED}Invalid choice. Please enter 1-5.{Colors.RESET}")


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
        help="Override default port (8720) - install only"
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
        else:  # menu — loop back after each action
            while True:
                command, _options = interactive_menu()
                if command == "quit":
                    print("\n  Goodbye!")
                    return EXIT_SUCCESS
                elif command == "install":
                    do_install()
                elif command == "reinstall":
                    do_reinstall()
                elif command == "uninstall":
                    do_uninstall()
                elif command == "test":
                    do_test()
                else:
                    continue
                # Pause so the user can read output before menu redraws
                input("\nPress Enter to return to menu...")
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
