"""Tests for config subcommand group."""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from pydantic import ValidationError
from typer.testing import CliRunner

from async_crud_mcp.cli.config_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.config_cmd.init_config")
def test_init_success(mock_init_config):
    """Test successful config initialization."""
    mock_init_config.return_value = Path("/tmp/config.json")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert "initialized" in result.stdout.lower()
    mock_init_config.assert_called_once()


@patch("async_crud_mcp.cli.config_cmd.init_config")
def test_init_exists(mock_init_config):
    """Test config init when config already exists."""
    mock_init_config.side_effect = FileExistsError("Config already exists")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 1
    assert "already exists" in result.stdout.lower()


@patch("async_crud_mcp.cli.config_cmd.init_config")
def test_init_with_port(mock_init_config):
    """Test config init with --port option."""
    mock_init_config.return_value = Path("/tmp/config.json")

    result = runner.invoke(app, ["init", "--port", "9000"])

    assert result.exit_code == 0
    mock_init_config.assert_called_once()
    call_kwargs = mock_init_config.call_args.kwargs
    assert call_kwargs["port"] == 9000


@patch("async_crud_mcp.cli.config_cmd.init_config")
def test_init_with_no_interactive(mock_init_config):
    """Test config init with --no-interactive option."""
    mock_init_config.return_value = Path("/tmp/config.json")

    result = runner.invoke(app, ["init", "--no-interactive"])

    assert result.exit_code == 0
    mock_init_config.assert_called_once()
    call_kwargs = mock_init_config.call_args.kwargs
    assert call_kwargs["interactive"] is False


@patch("async_crud_mcp.cli.config_cmd.init_config")
def test_init_with_username(mock_init_config):
    """Test config init with --username option."""
    mock_init_config.return_value = Path("/tmp/alice/config.json")

    result = runner.invoke(app, ["init", "--username", "alice"])

    assert result.exit_code == 0
    mock_init_config.assert_called_once()
    call_kwargs = mock_init_config.call_args.kwargs
    assert call_kwargs["username"] == "alice"


@patch("async_crud_mcp.cli.config_cmd.get_config_file_path")
@patch("builtins.open", new_callable=mock_open, read_data='{"daemon": {"enabled": true}}')
def test_show_success(mock_file, mock_get_path):
    """Test successful config display."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    result = runner.invoke(app, ["show"])

    assert result.exit_code == 0


@patch("async_crud_mcp.cli.config_cmd.get_config_file_path")
def test_show_not_found(mock_get_path):
    """Test show command when config doesn't exist."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    result = runner.invoke(app, ["show"])

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


@patch("async_crud_mcp.cli.config_cmd.get_config_file_path")
@patch("builtins.open", new_callable=mock_open, read_data='{"daemon": {"enabled": true}}')
def test_show_with_json(mock_file, mock_get_path):
    """Test show command with --json option."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    result = runner.invoke(app, ["show", "--json"])

    assert result.exit_code == 0
    assert '"daemon"' in result.stdout
    assert '"enabled"' in result.stdout


@patch("async_crud_mcp.cli.config_cmd.get_config_file_path_init")
@patch("builtins.open", new_callable=mock_open, read_data='{"daemon": {"enabled": true}}')
def test_show_with_username(mock_file, mock_get_path_init):
    """Test show command with --username option."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path_init.return_value = mock_path

    result = runner.invoke(app, ["show", "--username", "alice"])

    assert result.exit_code == 0
    mock_get_path_init.assert_called_once_with("alice")


@patch("async_crud_mcp.cli.config_cmd.get_settings")
@patch("async_crud_mcp.cli.config_cmd.get_config_file_path")
def test_validate_success(mock_get_path, mock_get_settings):
    """Test successful config validation."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    mock_settings = MagicMock()
    mock_settings.daemon.enabled = True
    mock_settings.daemon.host = "127.0.0.1"
    mock_settings.daemon.port = 8720
    mock_get_settings.return_value = mock_settings

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


@patch("async_crud_mcp.cli.config_cmd.get_settings")
@patch("async_crud_mcp.cli.config_cmd.get_config_file_path")
def test_validate_failure(mock_get_path, mock_get_settings):
    """Test failed config validation."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    mock_get_settings.side_effect = ValidationError.from_exception_data(
        "Settings", [{"type": "missing", "loc": ("daemon", "port"), "msg": "Field required"}]
    )

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 1
    assert "validation failed" in result.stdout.lower()


@patch("async_crud_mcp.cli.config_cmd.get_settings")
@patch("async_crud_mcp.cli.config_cmd.get_config_file_path_init")
def test_validate_with_username(mock_get_path_init, mock_get_settings):
    """Test validate command with --username option."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path_init.return_value = mock_path

    mock_settings = MagicMock()
    mock_settings.daemon.enabled = True
    mock_settings.daemon.host = "127.0.0.1"
    mock_settings.daemon.port = 8720
    mock_get_settings.return_value = mock_settings

    result = runner.invoke(app, ["validate", "--username", "alice"])

    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()
    mock_get_path_init.assert_called_once_with("alice")
