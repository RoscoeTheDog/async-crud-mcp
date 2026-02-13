"""Tests for setup subcommand group."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from async_crud_mcp.cli.setup_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
@patch("async_crud_mcp.cli.setup_cmd.Confirm.ask")
@patch("async_crud_mcp.cli.setup_cmd.Prompt.ask")
def test_wizard_new_config(
    mock_prompt,
    mock_confirm,
    mock_get_path,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
):
    """Test wizard with new config."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_prompt.side_effect = ["8720", "127.0.0.1", "sse", "INFO"]
    mock_confirm.return_value = True

    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()
    mock_init_config.assert_called_once()
    mock_installer.install.assert_called_once()
    mock_installer.start.assert_called_once()


@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
@patch("async_crud_mcp.cli.setup_cmd.Confirm.ask")
def test_wizard_existing_config_no_overwrite(mock_confirm, mock_get_path):
    """Test wizard with existing config, no overwrite."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    mock_confirm.side_effect = [False, False]

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "existing configuration" in result.stdout.lower()


@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
@patch("async_crud_mcp.cli.setup_cmd.Confirm.ask")
@patch("async_crud_mcp.cli.setup_cmd.Prompt.ask")
def test_wizard_no_install(
    mock_prompt,
    mock_confirm,
    mock_get_path,
    mock_find_port,
    mock_init_config,
):
    """Test wizard declining daemon installation."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_prompt.side_effect = ["8720", "127.0.0.1", "sse", "INFO"]
    mock_confirm.return_value = False

    mock_init_config.return_value = Path("/tmp/config.json")

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "daemon not installed" in result.stdout.lower()
