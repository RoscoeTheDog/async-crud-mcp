"""Tests for install subcommand group."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from async_crud_mcp.cli.install_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_success(mock_get_path, mock_init_config, mock_get_installer):
    """Test successful quick installation."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["quick-install", "--yes"])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()
    mock_init_config.assert_called_once()
    mock_installer.install.assert_called_once()
    mock_installer.start.assert_called_once()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_existing_config(mock_get_path, mock_get_installer):
    """Test quick install with existing config."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["quick-install", "--yes"])

    assert result.exit_code == 0
    assert "existing config" in result.stdout.lower()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
def test_uninstall_success(mock_get_installer):
    """Test successful uninstallation."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["uninstall", "--yes"])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()
    mock_installer.stop.assert_called_once()
    mock_installer.uninstall.assert_called_once()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
def test_uninstall_stop_failure(mock_get_installer):
    """Test uninstall when stop fails but uninstall succeeds."""
    mock_installer = MagicMock()
    mock_installer.stop.side_effect = OSError("Stop failed")
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["uninstall", "--yes"])

    assert result.exit_code == 0
    assert "warning" in result.stdout.lower()
    mock_installer.uninstall.assert_called_once()
