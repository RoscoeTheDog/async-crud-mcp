"""Tests for bootstrap subcommand group."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from async_crud_mcp.cli.bootstrap_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.bootstrap_cmd._check_admin")
@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_install_success(mock_get_installer, mock_check_admin):
    """Test successful daemon installation."""
    mock_check_admin.return_value = True
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 0
    assert "installed successfully" in result.stdout.lower()
    mock_installer.install.assert_called_once()


@patch("async_crud_mcp.cli.bootstrap_cmd._check_admin")
@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_install_failure(mock_get_installer, mock_check_admin):
    """Test failed daemon installation."""
    mock_check_admin.return_value = True
    mock_installer = MagicMock()
    mock_installer.install.side_effect = OSError("Installation failed")
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["install"])

    assert result.exit_code == 1
    assert "installation failed" in result.stdout.lower()


@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_start_success(mock_get_installer):
    """Test successful daemon start."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    assert "started successfully" in result.stdout.lower()
    mock_installer.start.assert_called_once()


@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_status_running(mock_get_installer):
    """Test status command with running daemon."""
    mock_installer = MagicMock()
    mock_installer.status.return_value = "RUNNING"
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "RUNNING" in result.stdout


@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_list_empty(mock_get_installer):
    """Test list command with no instances."""
    mock_installer = MagicMock()
    mock_installer.list.return_value = []
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "no daemon instances" in result.stdout.lower()


@patch("async_crud_mcp.cli.bootstrap_cmd.get_installer")
def test_list_with_instances(mock_get_installer):
    """Test list command with instances."""
    mock_installer = MagicMock()
    mock_installer.list.return_value = ["async-crud-mcp-daemon"]
    mock_installer.status.return_value = "RUNNING"
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "async-crud-mcp-daemon" in result.stdout
