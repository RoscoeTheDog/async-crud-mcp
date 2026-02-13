"""Tests for install subcommand group."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from async_crud_mcp.cli import app

runner = CliRunner()


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_success(mock_get_path, mock_init_config, mock_get_installer, mock_is_admin):
    """Test successful quick installation."""
    mock_is_admin.return_value = True  # Mock admin privileges
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


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_existing_config(mock_get_path, mock_get_installer, mock_is_admin):
    """Test quick install with existing config."""
    mock_is_admin.return_value = True  # Mock admin privileges
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


def test_version_command():
    """Test version command shows correct version."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "async-crud-mcp" in result.stdout
    assert "0.1.0" in result.stdout


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_with_force(mock_get_path, mock_init_config, mock_get_installer, mock_is_admin):
    """Test quick install with --force flag to overwrite existing config."""
    mock_is_admin.return_value = True  # Mock admin privileges
    mock_path = MagicMock()
    mock_path.exists.return_value = True  # Config already exists
    mock_get_path.return_value = mock_path

    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["quick-install", "--yes", "--force"])

    assert result.exit_code == 0
    # Verify init_config called with force=True
    mock_init_config.assert_called_once()
    call_kwargs = mock_init_config.call_args[1]
    assert call_kwargs.get('force') is True
    assert call_kwargs.get('interactive') is False


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_with_port(mock_get_path, mock_init_config, mock_get_installer, mock_is_admin):
    """Test quick install with --port flag to override default port."""
    mock_is_admin.return_value = True  # Mock admin privileges
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["quick-install", "--yes", "--port", "9000"])

    assert result.exit_code == 0
    # Verify init_config called with port=9000
    mock_init_config.assert_called_once()
    call_kwargs = mock_init_config.call_args[1]
    assert call_kwargs.get('port') == 9000
    assert call_kwargs.get('force') is False
    assert call_kwargs.get('interactive') is False


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_no_start(mock_get_path, mock_init_config, mock_get_installer, mock_is_admin):
    """Test quick install with --no-start flag skips starting daemon."""
    mock_is_admin.return_value = True  # Mock admin privileges
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, ["quick-install", "--yes", "--no-start"])

    assert result.exit_code == 0
    # Verify installer.start() was NOT called
    mock_installer.install.assert_called_once()
    mock_installer.start.assert_not_called()
    assert "skipped starting" in result.stdout.lower()


@patch("async_crud_mcp.cli.install_cmd._is_admin")
@patch("async_crud_mcp.cli.install_cmd.sys")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.init_config")
@patch("async_crud_mcp.cli.install_cmd.get_config_file_path")
def test_quick_install_admin_check_windows(mock_get_path, mock_init_config, mock_get_installer, mock_sys, mock_is_admin):
    """Test quick install fails on Windows without admin privileges."""
    mock_sys.platform = 'win32'
    mock_is_admin.return_value = False

    result = runner.invoke(app, ["quick-install", "--yes"])

    assert result.exit_code == 1
    assert "administrator" in result.stdout.lower()
    # Verify installer was NOT called
    mock_get_installer.assert_not_called()
    mock_init_config.assert_not_called()


@patch("async_crud_mcp.cli.install_cmd.shutil.rmtree")
@patch("async_crud_mcp.cli.install_cmd.get_config_dir")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
def test_uninstall_remove_config(mock_get_installer, mock_get_config_dir, mock_rmtree):
    """Test uninstall with --remove-config flag removes config directory."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    mock_config_dir = MagicMock()
    mock_config_dir.exists.return_value = True
    mock_get_config_dir.return_value = mock_config_dir

    result = runner.invoke(app, ["uninstall", "--yes", "--remove-config"])

    assert result.exit_code == 0
    # Verify shutil.rmtree called on config directory
    mock_rmtree.assert_called_once_with(mock_config_dir)
    assert "removed configuration" in result.stdout.lower()


@patch("async_crud_mcp.cli.install_cmd.shutil.rmtree")
@patch("async_crud_mcp.cli.install_cmd.get_logs_dir")
@patch("async_crud_mcp.cli.install_cmd.get_installer")
def test_uninstall_remove_logs(mock_get_installer, mock_get_logs_dir, mock_rmtree):
    """Test uninstall with --remove-logs flag removes logs directory."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    mock_logs_dir = MagicMock()
    mock_logs_dir.exists.return_value = True
    mock_get_logs_dir.return_value = mock_logs_dir

    result = runner.invoke(app, ["uninstall", "--yes", "--remove-logs"])

    assert result.exit_code == 0
    # Verify shutil.rmtree called on logs directory
    mock_rmtree.assert_called_once_with(mock_logs_dir)
    assert "removed logs" in result.stdout.lower()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
def test_uninstall_force_skips_confirm(mock_get_installer):
    """Test uninstall with --force flag skips confirmation."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    # Without --yes or --force, should prompt (but in test mode, prompt is auto-declined)
    # With --force, should skip prompt and proceed
    result = runner.invoke(app, ["uninstall", "--force"])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()
    mock_installer.uninstall.assert_called_once()


@patch("async_crud_mcp.cli.install_cmd.get_installer")
@patch("async_crud_mcp.cli.install_cmd.get_config_dir")
@patch("async_crud_mcp.cli.install_cmd.get_logs_dir")
def test_uninstall_keep_config_default(mock_get_logs_dir, mock_get_config_dir, mock_get_installer):
    """Test uninstall keeps config and logs by default."""
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    mock_config_dir = MagicMock()
    mock_config_dir.exists.return_value = True
    mock_get_config_dir.return_value = mock_config_dir

    mock_logs_dir = MagicMock()
    mock_logs_dir.exists.return_value = True
    mock_get_logs_dir.return_value = mock_logs_dir

    result = runner.invoke(app, ["uninstall", "--yes"])

    assert result.exit_code == 0
    # Verify config/logs directories were NOT checked (not removed)
    mock_get_config_dir.assert_not_called()
    mock_get_logs_dir.assert_not_called()
