"""Tests for scripts/installer.py."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Import functions from the installer script
scripts_dir = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

import installer


class TestCheckPrivileges:
    """Test privilege checking."""

    @patch("installer.platform.system", return_value="Windows")
    def test_check_privileges_windows_admin(self, mock_system):
        """Test Windows admin check returns True when admin."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        with patch.dict("sys.modules", {"ctypes": mock_ctypes}):
            assert installer.check_privileges() is True

    @patch("installer.platform.system", return_value="Windows")
    def test_check_privileges_windows_no_admin(self, mock_system):
        """Test Windows admin check returns False when not admin."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 0
        with patch.dict("sys.modules", {"ctypes": mock_ctypes}):
            assert installer.check_privileges() is False

    @patch("installer.platform.system", return_value="Linux")
    def test_check_privileges_non_windows(self, mock_system):
        """Test non-Windows always returns True (user-level services)."""
        assert installer.check_privileges() is True

    @patch("installer.platform.system", return_value="Darwin")
    def test_check_privileges_macos(self, mock_system):
        """Test macOS always returns True."""
        assert installer.check_privileges() is True


class TestRunPreflightChecks:
    """Test preflight check logic."""

    def test_run_preflight_checks_all_pass(self, tmp_path):
        """Test all preflight checks pass with valid environment."""
        target_dir = tmp_path / "install"
        target_dir.mkdir()
        results = installer.run_preflight_checks(target_dir)

        assert len(results) == 3
        # Python version check (we're running >= 3.10 in test env)
        assert results[0][0] == "Python version"
        assert results[0][1] is True
        # Disk space
        assert results[1][0] == "Disk space"
        assert results[1][1] is True
        # Write permissions
        assert results[2][0] == "Write permissions"
        assert results[2][1] is True

    def test_run_preflight_checks_python_version_check(self, tmp_path):
        """Test Python version is checked against 3.10."""
        target_dir = tmp_path / "install"
        target_dir.mkdir()

        fake_version = MagicMock()
        fake_version.__ge__ = lambda self, other: (3, 9) >= other
        fake_version.major = 3
        fake_version.minor = 9

        with patch.object(installer.sys, "version_info", fake_version):
            results = installer.run_preflight_checks(target_dir)
            assert results[0][1] is False
            assert "need >= 3.10" in results[0][2]


class TestGetPlatformPaths:
    """Test platform-specific path resolution."""

    @patch("installer.platform.system", return_value="Windows")
    @patch.dict("os.environ", {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"})
    def test_get_platform_paths_windows(self, mock_system):
        """Test Windows paths use LOCALAPPDATA."""
        paths = installer.get_platform_paths()
        assert "async-crud-mcp" in str(paths["base_dir"])
        assert paths["venv_dir"] == paths["base_dir"] / "venv"
        assert paths["config_file"] == paths["config_dir"] / "config.json"

    @patch("installer.platform.system", return_value="Linux")
    @patch.dict("os.environ", {
        "XDG_CONFIG_HOME": "/home/test/.config",
        "XDG_DATA_HOME": "/home/test/.local/share",
    })
    def test_get_platform_paths_linux(self, mock_system):
        """Test Linux paths use XDG directories."""
        paths = installer.get_platform_paths()
        assert ".config" in str(paths["config_dir"])
        assert "async-crud-mcp" in str(paths["config_dir"])
        assert paths["venv_dir"] == paths["base_dir"] / "venv"

    @patch("installer.platform.system", return_value="Darwin")
    def test_get_platform_paths_macos(self, mock_system):
        """Test macOS paths use Library/Application Support."""
        paths = installer.get_platform_paths()
        assert "Library" in str(paths["base_dir"])
        assert "Application Support" in str(paths["base_dir"])


class TestBootstrapUv:
    """Test uv bootstrap."""

    @patch("installer.subprocess.run")
    def test_bootstrap_uv_success(self, mock_run):
        """Test successful uv bootstrap."""
        mock_run.return_value = MagicMock(stdout="uv installed", returncode=0)
        assert installer.bootstrap_uv() is True
        mock_run.assert_called_once()

    @patch("installer.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", stderr="fail"))
    def test_bootstrap_uv_failure(self, mock_run):
        """Test failed uv bootstrap."""
        assert installer.bootstrap_uv() is False


class TestCreateVenv:
    """Test virtual environment creation."""

    @patch("installer.subprocess.run")
    def test_create_venv_success(self, mock_run):
        """Test successful venv creation."""
        mock_run.return_value = MagicMock(returncode=0)
        assert installer.create_venv(Path("/fake/venv")) is True
        args = mock_run.call_args[0][0]
        assert "uv" in args[0]
        assert "venv" in args[1]

    @patch("installer.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", stderr="fail"))
    def test_create_venv_failure(self, mock_run):
        """Test failed venv creation."""
        assert installer.create_venv(Path("/fake/venv")) is False


class TestInstallPackage:
    """Test package installation."""

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run")
    def test_install_package_success(self, mock_run, mock_system):
        """Test successful package installation."""
        mock_run.return_value = MagicMock(returncode=0)
        assert installer.install_package(Path("C:\\fake\\venv")) is True
        args = mock_run.call_args[0][0]
        assert "uv" in args[0]
        assert "pip" in args[1]
        assert "install" in args[2]

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run")
    def test_install_package_not_editable(self, mock_run, mock_system):
        """ADR-015 C1: Package must NOT be installed in editable mode."""
        mock_run.return_value = MagicMock(returncode=0)
        installer.install_package(Path("C:\\fake\\venv"))
        args = mock_run.call_args[0][0]
        assert "-e" not in args, (
            "ADR-015 C1: installer must not use -e (editable install). "
            "Editable installs break Windows service (LocalSystem can't access dev paths)."
        )


class TestGetBasePythonDir:
    """Test _get_base_python_dir helper."""

    def test_returns_home_dir_from_pyvenv_cfg(self, tmp_path):
        """Test parsing home key from pyvenv.cfg."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        # Create a fake base python dir
        base_dir = tmp_path / "python"
        base_dir.mkdir()
        # Write pyvenv.cfg
        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {base_dir}\nimplementation = CPython\n",
            encoding="utf-8",
        )
        result = installer._get_base_python_dir(venv_dir)
        assert result == base_dir

    def test_returns_none_when_no_cfg(self, tmp_path):
        """Test returns None when pyvenv.cfg missing."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        assert installer._get_base_python_dir(venv_dir) is None

    def test_returns_none_when_home_dir_missing(self, tmp_path):
        """Test returns None when home dir doesn't exist."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        missing_dir = tmp_path / "this_dir_does_not_exist"
        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {missing_dir}\n", encoding="utf-8"
        )
        assert installer._get_base_python_dir(venv_dir) is None


class TestConfigurePywin32Dlls:
    """Test pywin32 DLL configuration."""

    @patch("installer.platform.system", return_value="Linux")
    def test_configure_pywin32_dlls_non_windows_noop(self, mock_system):
        """Test non-Windows is a no-op returning True."""
        assert installer.configure_pywin32_dlls(Path("/fake/venv")) is True

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.shutil.copy2")
    def test_configure_pywin32_dlls_copies_files(self, mock_copy, mock_system, tmp_path):
        """Test Windows DLL copy when pywin32 is present."""
        venv_dir = tmp_path / "venv"
        site_packages = venv_dir / "Lib" / "site-packages"
        pywin32_system32 = site_packages / "pywin32_system32"
        pywin32_system32.mkdir(parents=True)

        # Create fake DLLs
        (pywin32_system32 / "pywintypes310.dll").touch()
        (pywin32_system32 / "pythoncom310.dll").touch()

        # Create win32 dir with pythonservice.exe
        pywin32_win32 = site_packages / "win32"
        pywin32_win32.mkdir(parents=True)
        (pywin32_win32 / "pythonservice.exe").touch()

        assert installer.configure_pywin32_dlls(venv_dir) is True
        assert mock_copy.call_count == 3  # 2 DLLs + 1 exe

    @patch("installer.platform.system", return_value="Windows")
    def test_configure_pywin32_dlls_copies_core_python_dlls(self, mock_system, tmp_path):
        """Test core Python DLLs are copied from base Python dir."""
        venv_dir = tmp_path / "venv"
        site_packages = venv_dir / "Lib" / "site-packages"
        pywin32_system32 = site_packages / "pywin32_system32"
        pywin32_system32.mkdir(parents=True)
        pywin32_win32 = site_packages / "win32"
        pywin32_win32.mkdir(parents=True)

        # Create minimal pywin32 files
        (pywin32_system32 / "pywintypes312.dll").write_bytes(b"fake")
        (pywin32_system32 / "pythoncom312.dll").write_bytes(b"fake")
        (pywin32_win32 / "pythonservice.exe").write_bytes(b"fake")

        # Create fake base Python dir with core DLLs
        base_dir = tmp_path / "python"
        base_dir.mkdir()
        (base_dir / "python3.dll").write_bytes(b"python3")
        (base_dir / "python312.dll").write_bytes(b"python312")
        (base_dir / "vcruntime140.dll").write_bytes(b"vcrt")

        # Write pyvenv.cfg
        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {base_dir}\n", encoding="utf-8"
        )

        assert installer.configure_pywin32_dlls(venv_dir) is True

        # Verify core DLLs were copied
        assert (venv_dir / "python3.dll").exists()
        assert (venv_dir / "python312.dll").exists()
        assert (venv_dir / "vcruntime140.dll").exists()

    @patch("installer.platform.system", return_value="Windows")
    def test_configure_pywin32_dlls_skips_existing_core_dlls(self, mock_system, tmp_path):
        """Test core Python DLLs are not overwritten if already present."""
        venv_dir = tmp_path / "venv"
        site_packages = venv_dir / "Lib" / "site-packages"
        pywin32_system32 = site_packages / "pywin32_system32"
        pywin32_system32.mkdir(parents=True)

        (pywin32_system32 / "pywintypes312.dll").write_bytes(b"fake")

        # Pre-existing DLL in venv root
        (venv_dir / "python312.dll").write_bytes(b"original")

        # Base Python dir
        base_dir = tmp_path / "python"
        base_dir.mkdir()
        (base_dir / "python312.dll").write_bytes(b"new-version")

        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {base_dir}\n", encoding="utf-8"
        )

        assert installer.configure_pywin32_dlls(venv_dir) is True
        # Should keep the original, not overwrite
        assert (venv_dir / "python312.dll").read_bytes() == b"original"

    @patch("installer.platform.system", return_value="Windows")
    def test_configure_pywin32_dlls_missing_dir(self, mock_system, tmp_path):
        """Test Windows with missing pywin32 directory skips gracefully."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        # No Lib/site-packages/pywin32_system32
        assert installer.configure_pywin32_dlls(venv_dir) is True


class TestInitConfig:
    """Test configuration initialization."""

    def test_init_config_creates_new(self, tmp_path):
        """Test creating a new config file."""
        config_dir = tmp_path / "config"
        config_file = config_dir / "config.json"

        assert installer.init_config(config_dir, config_file) is True
        assert config_file.exists()

        data = json.loads(config_file.read_text())
        assert data["daemon"]["host"] == "127.0.0.1"
        assert data["daemon"]["port"] == 8720

    def test_init_config_with_custom_port(self, tmp_path):
        """Test creating config with custom port."""
        config_dir = tmp_path / "config"
        config_file = config_dir / "config.json"

        assert installer.init_config(config_dir, config_file, port=9000) is True
        data = json.loads(config_file.read_text())
        assert data["daemon"]["port"] == 9000

    def test_init_config_existing_skips(self, tmp_path):
        """Test that existing config is not overwritten."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text('{"existing": true}')

        assert installer.init_config(config_dir, config_file) is True
        data = json.loads(config_file.read_text())
        assert data == {"existing": True}


class TestInstallService:
    """Test service installation via Python API."""

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run")
    def test_install_service_success(self, mock_run, mock_system, tmp_path):
        """Test successful service installation."""
        mock_run.return_value = MagicMock(returncode=0)
        venv_dir = tmp_path / "venv"

        assert installer.install_service(venv_dir) is True
        args = mock_run.call_args[0][0]
        assert "python.exe" in args[0] or "python" in args[0]
        assert "get_installer" in args[2]
        assert "install()" in args[2]

    @patch("installer.platform.system", return_value="Linux")
    @patch("installer.subprocess.run")
    def test_install_service_linux_python_path(self, mock_run, mock_system, tmp_path):
        """Test Linux uses bin/python path."""
        mock_run.return_value = MagicMock(returncode=0)
        venv_dir = tmp_path / "venv"

        assert installer.install_service(venv_dir) is True
        python_path = mock_run.call_args[0][0][0]
        assert "bin" in python_path
        assert "python" in python_path

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", stderr="service error"))
    def test_install_service_failure(self, mock_run, mock_system, tmp_path):
        """Test failed service installation."""
        venv_dir = tmp_path / "venv"
        assert installer.install_service(venv_dir) is False


class TestDoInstall:
    """Test full installation flow."""

    @patch("installer.do_configure", return_value=0)
    @patch("installer.start_service", return_value=True)
    @patch("installer.install_service", return_value=True)
    @patch("installer.init_config", return_value=True)
    @patch("installer.verify_package_import", return_value=True)
    @patch("installer.configure_pywin32_dlls", return_value=True)
    @patch("installer.install_package", return_value=True)
    @patch("installer.create_venv", return_value=True)
    @patch("installer.bootstrap_uv", return_value=True)
    @patch("installer.run_preflight_checks", return_value=[
        ("Python version", True, "OK"),
        ("Disk space", True, "OK"),
        ("Write permissions", True, "OK"),
    ])
    @patch("installer.check_privileges", return_value=True)
    @patch("installer.get_platform_paths")
    def test_do_install_success(self, mock_paths, mock_priv, mock_preflight,
                                mock_uv, mock_venv, mock_pkg, mock_pywin,
                                mock_verify, mock_config, mock_svc,
                                mock_start, mock_configure):
        """Test successful full installation."""
        mock_paths.return_value = {
            "base_dir": Path("/fake/base"),
            "config_dir": Path("/fake/config"),
            "log_dir": Path("/fake/logs"),
            "venv_dir": Path("/fake/venv"),
            "config_file": Path("/fake/config/config.json"),
        }

        result = installer.do_install()
        assert result == installer.EXIT_SUCCESS
        mock_svc.assert_called_once_with(Path("/fake/venv"))
        mock_start.assert_called_once()

    @patch("installer.run_preflight_checks", return_value=[
        ("Python version", False, "Python 3.9"),
        ("Disk space", True, "OK"),
        ("Write permissions", True, "OK"),
    ])
    @patch("installer.check_privileges", return_value=True)
    @patch("installer.get_platform_paths")
    def test_do_install_preflight_failure(self, mock_paths, mock_priv, mock_preflight):
        """Test installation fails on preflight check failure."""
        mock_paths.return_value = {
            "base_dir": Path("/fake/base"),
            "config_dir": Path("/fake/config"),
            "log_dir": Path("/fake/logs"),
            "venv_dir": Path("/fake/venv"),
            "config_file": Path("/fake/config/config.json"),
        }

        result = installer.do_install()
        assert result == installer.EXIT_FAILED


class TestCreatePthFile:
    """Test _create_pth_file helper."""

    def test_creates_pth_file_with_correct_contents(self, tmp_path):
        """Test _pth file includes stdlib and venv paths."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        # Create a fake versioned Python DLL
        (venv_dir / "python312.dll").write_bytes(b"fake")

        # Create base Python dir with stdlib
        base_dir = tmp_path / "python"
        base_dir.mkdir()
        (base_dir / "Lib").mkdir()
        (base_dir / "DLLs").mkdir()
        (base_dir / "python312.zip").write_bytes(b"fake")

        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {base_dir}\n", encoding="utf-8"
        )

        installer._create_pth_file(venv_dir)

        pth_file = venv_dir / "python312._pth"
        assert pth_file.exists()
        contents = pth_file.read_text(encoding="utf-8")
        lines = contents.splitlines()
        # Base Python stdlib paths (absolute)
        assert str(base_dir / "python312.zip") in lines
        assert str(base_dir / "Lib") in lines
        assert str(base_dir / "DLLs") in lines
        # Venv-local paths (relative)
        assert "." in lines
        assert "Lib\\site-packages" in lines
        assert "Lib\\site-packages\\win32" in lines
        assert "Lib\\site-packages\\win32\\lib" in lines
        assert "Lib\\site-packages\\Pythonwin" in lines
        assert "import site" in lines

    def test_detects_python_version_from_dll(self, tmp_path):
        """Test _pth filename matches the versioned DLL name."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        # Simulate Python 3.13
        (venv_dir / "python3.dll").write_bytes(b"generic")
        (venv_dir / "python313.dll").write_bytes(b"versioned")

        installer._create_pth_file(venv_dir)

        # Should create python313._pth, NOT python3._pth
        assert (venv_dir / "python313._pth").exists()
        assert not (venv_dir / "python3._pth").exists()

    def test_skips_when_no_versioned_dll(self, tmp_path):
        """Test graceful skip when no versioned python3XX.dll found."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        # Only python3.dll (generic), no versioned DLL
        (venv_dir / "python3.dll").write_bytes(b"generic")

        installer._create_pth_file(venv_dir)

        # Should not create any _pth file
        pth_files = list(venv_dir.glob("*._pth"))
        assert len(pth_files) == 0

    def test_works_without_pyvenv_cfg(self, tmp_path):
        """Test _pth file created with venv paths even without base Python."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "python312.dll").write_bytes(b"fake")
        # No pyvenv.cfg - base Python dir unknown

        installer._create_pth_file(venv_dir)

        pth_file = venv_dir / "python312._pth"
        assert pth_file.exists()
        contents = pth_file.read_text(encoding="utf-8")
        # Should still have venv-local paths
        assert "Lib\\site-packages\\win32" in contents
        assert "import site" in contents

    @patch("installer.platform.system", return_value="Windows")
    def test_configure_pywin32_dlls_creates_pth(self, mock_system, tmp_path):
        """Test configure_pywin32_dlls creates _pth file end-to-end."""
        venv_dir = tmp_path / "venv"
        site_packages = venv_dir / "Lib" / "site-packages"
        pywin32_system32 = site_packages / "pywin32_system32"
        pywin32_system32.mkdir(parents=True)
        pywin32_win32 = site_packages / "win32"
        pywin32_win32.mkdir(parents=True)

        # Create minimal pywin32 files
        (pywin32_system32 / "pywintypes312.dll").write_bytes(b"fake")
        (pywin32_system32 / "pythoncom312.dll").write_bytes(b"fake")
        (pywin32_win32 / "pythonservice.exe").write_bytes(b"fake")

        # Create base Python dir with core DLLs and stdlib
        base_dir = tmp_path / "python"
        base_dir.mkdir()
        (base_dir / "python3.dll").write_bytes(b"python3")
        (base_dir / "python312.dll").write_bytes(b"python312")
        (base_dir / "Lib").mkdir()
        (base_dir / "DLLs").mkdir()

        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {base_dir}\n", encoding="utf-8"
        )

        assert installer.configure_pywin32_dlls(venv_dir) is True

        # Verify _pth file was created with both stdlib and win32 paths
        pth_file = venv_dir / "python312._pth"
        assert pth_file.exists()
        contents = pth_file.read_text(encoding="utf-8")
        assert str(base_dir / "Lib") in contents
        assert "Lib\\site-packages\\win32" in contents


class TestStartService:
    """Test service start functionality."""

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run")
    def test_start_service_windows_success(self, mock_run, mock_system):
        """Test successful Windows service start."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assert installer.start_service() is True
        args = mock_run.call_args[0][0]
        assert args == ["sc", "start", "async-crud-mcp-daemon"]

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run")
    def test_start_service_windows_failure(self, mock_run, mock_system):
        """Test Windows service start failure returns False."""
        mock_run.return_value = MagicMock(returncode=1, stderr="Access denied")
        assert installer.start_service() is False

    @patch("installer.platform.system", return_value="Linux")
    @patch("installer.subprocess.run")
    def test_start_service_linux(self, mock_run, mock_system):
        """Test Linux service start uses systemctl."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assert installer.start_service() is True
        args = mock_run.call_args[0][0]
        assert "systemctl" in args[0]
        assert "start" in args

    @patch("installer.platform.system", return_value="Windows")
    @patch("installer.subprocess.run", side_effect=Exception("subprocess error"))
    def test_start_service_exception(self, mock_run, mock_system):
        """Test start_service handles exceptions gracefully."""
        assert installer.start_service() is False
