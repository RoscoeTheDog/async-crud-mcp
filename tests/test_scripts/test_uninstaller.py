"""Tests for scripts/uninstaller.py."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import functions from the uninstaller script
scripts_dir = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

import uninstaller


class TestGetPlatformPaths:
    """Test platform-specific path resolution."""

    @patch("uninstaller.platform.system", return_value="Windows")
    @patch.dict("os.environ", {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"})
    def test_get_platform_paths_windows(self, mock_system):
        """Test Windows paths use LOCALAPPDATA."""
        paths = uninstaller.get_platform_paths()
        assert "async-crud-mcp" in str(paths["base_dir"])
        assert paths["venv_dir"] == paths["base_dir"] / "venv"
        assert paths["config_file"] == paths["config_dir"] / "config.json"

    @patch("uninstaller.platform.system", return_value="Linux")
    @patch.dict("os.environ", {
        "XDG_CONFIG_HOME": "/home/test/.config",
        "XDG_DATA_HOME": "/home/test/.local/share",
    })
    def test_get_platform_paths_linux(self, mock_system):
        """Test Linux paths use XDG directories."""
        paths = uninstaller.get_platform_paths()
        assert ".config" in str(paths["config_dir"])
        assert "async-crud-mcp" in str(paths["config_dir"])


class TestStopDaemon:
    """Test daemon stopping."""

    @patch("uninstaller.platform.system", return_value="Windows")
    @patch("uninstaller.subprocess.run")
    def test_stop_daemon_windows(self, mock_run, mock_system):
        """Test stopping Windows service."""
        mock_run.return_value = MagicMock(returncode=0)
        assert uninstaller.stop_daemon() is True
        args = mock_run.call_args[0][0]
        assert "sc" in args[0]
        assert "stop" in args[1]

    @patch("uninstaller.platform.system", return_value="Linux")
    @patch("uninstaller.subprocess.run")
    def test_stop_daemon_linux(self, mock_run, mock_system):
        """Test stopping systemd service."""
        mock_run.return_value = MagicMock(returncode=0)
        assert uninstaller.stop_daemon() is True
        args = mock_run.call_args[0][0]
        assert "systemctl" in args[0]
        assert "--user" in args[1]

    @patch("uninstaller.platform.system", return_value="Darwin")
    @patch("uninstaller.subprocess.run")
    def test_stop_daemon_macos(self, mock_run, mock_system):
        """Test stopping launchd service."""
        mock_run.return_value = MagicMock(returncode=0)
        assert uninstaller.stop_daemon() is True
        args = mock_run.call_args[0][0]
        assert "launchctl" in args[0]


class TestUninstallService:
    """Test service uninstallation via Python API."""

    @patch("uninstaller.platform.system", return_value="Windows")
    @patch("uninstaller.subprocess.run")
    def test_uninstall_service_success(self, mock_run, mock_system, tmp_path):
        """Test successful service uninstallation."""
        mock_run.return_value = MagicMock(returncode=0)
        venv_dir = tmp_path / "venv"
        # Create the expected python path so the exists() check passes
        python_path = venv_dir / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True)
        python_path.touch()

        assert uninstaller.uninstall_service(venv_dir) is True
        args = mock_run.call_args[0][0]
        assert "get_installer" in args[2]
        assert "uninstall()" in args[2]

    @patch("uninstaller.platform.system", return_value="Linux")
    @patch("uninstaller.subprocess.run")
    def test_uninstall_service_linux(self, mock_run, mock_system, tmp_path):
        """Test Linux uses bin/python path."""
        mock_run.return_value = MagicMock(returncode=0)
        venv_dir = tmp_path / "venv"
        python_path = venv_dir / "bin" / "python"
        python_path.parent.mkdir(parents=True)
        python_path.touch()

        assert uninstaller.uninstall_service(venv_dir) is True
        called_python = mock_run.call_args[0][0][0]
        assert "bin" in called_python

    @patch("uninstaller.platform.system", return_value="Windows")
    @patch("uninstaller.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", stderr="error"))
    def test_uninstall_service_failure(self, mock_run, mock_system, tmp_path):
        """Test failed service uninstallation."""
        venv_dir = tmp_path / "venv"
        python_path = venv_dir / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True)
        python_path.touch()

        assert uninstaller.uninstall_service(venv_dir) is False

    @patch("uninstaller.platform.system", return_value="Windows")
    def test_uninstall_service_missing_venv(self, mock_system, tmp_path):
        """Test uninstall skips when venv python doesn't exist."""
        venv_dir = tmp_path / "venv"
        # Don't create python.exe
        assert uninstaller.uninstall_service(venv_dir) is False


class TestRemoveVenv:
    """Test virtual environment removal."""

    def test_remove_venv_exists(self, tmp_path):
        """Test removing an existing venv directory."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "some_file.txt").touch()

        assert uninstaller.remove_venv(venv_dir) is True
        assert not venv_dir.exists()

    def test_remove_venv_missing(self, tmp_path):
        """Test removing a non-existent venv is a no-op success."""
        venv_dir = tmp_path / "venv"
        assert uninstaller.remove_venv(venv_dir) is True


class TestRemoveConfig:
    """Test configuration removal."""

    def test_remove_config_with_confirm(self, tmp_path):
        """Test removing config with skip_confirm=True."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")

        assert uninstaller.remove_config(config_dir, skip_confirm=True) is True
        assert not config_dir.exists()

    @patch("builtins.input", return_value="n")
    def test_remove_config_skip_confirm(self, mock_input, tmp_path):
        """Test declining config removal keeps files."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")

        assert uninstaller.remove_config(config_dir, skip_confirm=False) is True
        assert config_dir.exists()

    def test_remove_config_missing_dir(self, tmp_path):
        """Test removing non-existent config dir is a no-op success."""
        config_dir = tmp_path / "nonexistent"
        assert uninstaller.remove_config(config_dir) is True
