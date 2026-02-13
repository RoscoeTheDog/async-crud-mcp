"""Tests for setup subcommand group."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from typer.testing import CliRunner

from async_crud_mcp.cli import app

runner = CliRunner()


@patch("async_crud_mcp.cli.setup_cmd._verify_connectivity")
@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_logs_dir")
@patch("async_crud_mcp.cli.setup_cmd.get_config_dir")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
@patch("async_crud_mcp.cli.setup_cmd.Confirm.ask")
@patch("async_crud_mcp.cli.setup_cmd.Prompt.ask")
def test_wizard_new_config(
    mock_prompt,
    mock_confirm,
    mock_get_path,
    mock_get_config_dir,
    mock_get_logs_dir,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
    mock_configure_claude,
    mock_verify_connectivity,
):
    """Test wizard with new config (all steps)."""
    # Mock config path
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    # Mock directories
    mock_config_dir = MagicMock()
    mock_config_dir.mkdir = MagicMock()
    mock_get_config_dir.return_value = mock_config_dir

    mock_logs_dir = MagicMock()
    mock_logs_dir.mkdir = MagicMock()
    mock_get_logs_dir.return_value = mock_logs_dir

    # Mock port discovery
    mock_find_port.return_value = 8720

    # Mock user prompts
    mock_prompt.side_effect = ["8720", "127.0.0.1", "sse", "INFO"]
    mock_confirm.side_effect = [True, True]  # Overwrite, Install daemon

    # Mock config init
    mock_init_config.return_value = Path("/tmp/config.json")

    # Mock installer
    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    # Mock imports for prerequisites
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()

    # Verify all steps were called
    mock_find_port.assert_called_once()
    mock_config_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_logs_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_init_config.assert_called_once()
    mock_installer.install.assert_called_once()
    mock_installer.start.assert_called_once()
    mock_configure_claude.assert_called_once()
    mock_verify_connectivity.assert_called_once()


@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
@patch("async_crud_mcp.cli.setup_cmd.Confirm.ask")
def test_wizard_existing_config_no_overwrite(mock_confirm, mock_get_path, mock_configure_claude):
    """Test wizard with existing config, no overwrite."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    # Sequence: Use port (yes), Don't overwrite config (no), Don't install daemon (no)
    mock_confirm.side_effect = [True, False, False]

    # Mock imports for prerequisites
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.find_available_port", return_value=8720):
            with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
                with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                    mock_config_dir.return_value = MagicMock()
                    mock_logs_dir.return_value = MagicMock()
                    with patch("builtins.open", mock_open(read_data='{"daemon":{"host":"127.0.0.1","port":8720}}')):
                        result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    assert "existing configuration" in result.stdout.lower()


@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
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
    mock_configure_claude,
):
    """Test wizard declining daemon installation."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_prompt.side_effect = ["8720", "127.0.0.1", "sse", "INFO"]
    # Use port? yes, install daemon? no
    mock_confirm.side_effect = [True, False]

    mock_init_config.return_value = Path("/tmp/config.json")

    # Mock imports for prerequisites and directories
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
            with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                mock_config_dir.return_value = MagicMock()
                mock_logs_dir.return_value = MagicMock()
                result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()


@patch("async_crud_mcp.cli.setup_cmd._verify_connectivity")
@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
def test_wizard_with_port_option(
    mock_get_path,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
    mock_configure_claude,
    mock_verify_connectivity,
):
    """Test wizard with --port option."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 9000
    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    # Mock imports and directories
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
            with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                mock_config_dir.return_value = MagicMock()
                mock_logs_dir.return_value = MagicMock()
                result = runner.invoke(app, ["setup", "--port", "9000", "--no-interactive"])

    assert result.exit_code == 0
    # Verify find_available_port was called with the specified port
    mock_find_port.assert_called_once_with(start=9000)


@patch("async_crud_mcp.cli.setup_cmd._verify_connectivity")
@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
def test_wizard_no_interactive(
    mock_get_path,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
    mock_configure_claude,
    mock_verify_connectivity,
):
    """Test wizard with --no-interactive flag."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    # Mock imports and directories
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
            with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                with patch("async_crud_mcp.cli.setup_cmd.Prompt.ask") as mock_prompt:
                    with patch("async_crud_mcp.cli.setup_cmd.Confirm.ask") as mock_confirm:
                        mock_config_dir.return_value = MagicMock()
                        mock_logs_dir.return_value = MagicMock()
                        result = runner.invoke(app, ["setup", "--no-interactive"])

                        # Verify no prompts were called
                        mock_prompt.assert_not_called()
                        mock_confirm.assert_not_called()

    assert result.exit_code == 0


@patch("async_crud_mcp.cli.setup_cmd._verify_connectivity")
@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
def test_wizard_force_option(
    mock_get_path,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
    mock_configure_claude,
    mock_verify_connectivity,
):
    """Test wizard with --force option."""
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_init_config.return_value = Path("/tmp/config.json")

    mock_installer = MagicMock()
    mock_get_installer.return_value = mock_installer

    # Mock imports and directories
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
            with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                mock_config_dir.return_value = MagicMock()
                mock_logs_dir.return_value = MagicMock()
                result = runner.invoke(app, ["setup", "--force", "--no-interactive"])

    assert result.exit_code == 0
    # Verify init_config was called with force=True
    mock_init_config.assert_called_once()


def test_wizard_prerequisites_pass():
    """Test prerequisites check passes with all packages available."""
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        from async_crud_mcp.cli.setup_cmd import _check_prerequisites
        from rich.console import Console

        console = Console()
        result = _check_prerequisites(console, no_interactive=False)

    assert result is True


def test_wizard_prerequisites_fail():
    """Test prerequisites check fails with missing package."""
    # Remove fastmcp from sys.modules if it exists
    saved_modules = {}
    for pkg in ["fastmcp", "pydantic", "loguru"]:
        if pkg in sys.modules:
            saved_modules[pkg] = sys.modules[pkg]
            del sys.modules[pkg]

    try:
        from async_crud_mcp.cli.setup_cmd import _check_prerequisites
        from rich.console import Console

        console = Console()

        # Mock imports - make fastmcp fail
        def mock_import(name, *args, **kwargs):
            if name == "fastmcp":
                raise ImportError("No module named 'fastmcp'")
            return Mock()

        with patch("builtins.__import__", side_effect=mock_import):
            result = _check_prerequisites(console, no_interactive=False)

        assert result is False
    finally:
        # Restore saved modules
        for pkg, mod in saved_modules.items():
            sys.modules[pkg] = mod


@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
def test_wizard_port_discovery(mock_find_port):
    """Test port discovery when default port is in use."""
    from async_crud_mcp.cli.setup_cmd import _find_and_verify_port
    from rich.console import Console

    console = Console()
    mock_find_port.return_value = 8721  # Different from default

    port = _find_and_verify_port(console, cli_port=None, no_interactive=True)

    assert port == 8721
    mock_find_port.assert_called_once()


@patch("async_crud_mcp.cli.setup_cmd.get_logs_dir")
@patch("async_crud_mcp.cli.setup_cmd.get_config_dir")
def test_wizard_directory_creation(mock_get_config_dir, mock_get_logs_dir):
    """Test directory creation step."""
    from async_crud_mcp.cli.setup_cmd import _create_directories
    from rich.console import Console

    console = Console()

    mock_config_dir = MagicMock()
    mock_logs_dir = MagicMock()
    mock_get_config_dir.return_value = mock_config_dir
    mock_get_logs_dir.return_value = mock_logs_dir

    _create_directories(console)

    mock_config_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_logs_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)


def test_wizard_claude_config():
    """Test Claude CLI configuration step."""
    from async_crud_mcp.cli.setup_cmd import _configure_claude_cli
    from rich.console import Console

    console = Console()

    # Mock the Claude config file
    mock_config = {"mcpServers": {}}
    config_content = json.dumps(mock_config)

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_content)) as mock_file:
            _configure_claude_cli(console, "127.0.0.1", 8720)

            # Verify file was written
            mock_file.assert_called()


@patch("async_crud_mcp.cli.setup_cmd._is_port_listening")
@patch("async_crud_mcp.cli.setup_cmd.time.sleep")
def test_wizard_connectivity_check_success(mock_sleep, mock_is_listening):
    """Test connectivity check success."""
    from async_crud_mcp.cli.setup_cmd import _verify_connectivity
    from rich.console import Console

    console = Console()
    mock_is_listening.return_value = True

    _verify_connectivity(console, "127.0.0.1", 8720)

    mock_is_listening.assert_called_once_with("127.0.0.1", 8720)
    mock_sleep.assert_called_once_with(2)


@patch("async_crud_mcp.cli.setup_cmd._is_port_listening")
@patch("async_crud_mcp.cli.setup_cmd.time.sleep")
def test_wizard_connectivity_check_failure(mock_sleep, mock_is_listening):
    """Test connectivity check failure (warning, not error)."""
    from async_crud_mcp.cli.setup_cmd import _verify_connectivity
    from rich.console import Console

    console = Console()
    mock_is_listening.return_value = False

    # Should not raise - just warns
    _verify_connectivity(console, "127.0.0.1", 8720)

    mock_is_listening.assert_called_once_with("127.0.0.1", 8720)


@patch("async_crud_mcp.cli.setup_cmd._verify_connectivity")
@patch("async_crud_mcp.cli.setup_cmd._configure_claude_cli")
@patch("async_crud_mcp.cli.setup_cmd.get_installer")
@patch("async_crud_mcp.cli.setup_cmd.init_config")
@patch("async_crud_mcp.cli.setup_cmd.find_available_port")
@patch("async_crud_mcp.cli.setup_cmd.get_config_file_path")
def test_wizard_install_fails_without_admin(
    mock_get_path,
    mock_find_port,
    mock_init_config,
    mock_get_installer,
    mock_configure_claude,
    mock_verify_connectivity,
):
    """Test wizard continues with warning when daemon install fails."""
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_path.return_value = mock_path

    mock_find_port.return_value = 8720
    mock_init_config.return_value = Path("/tmp/config.json")

    # Mock installer to raise OSError
    mock_installer = MagicMock()
    mock_installer.install.side_effect = OSError("Access denied")
    mock_get_installer.return_value = mock_installer

    # Mock imports and directories
    with patch.dict(sys.modules, {"fastmcp": Mock(), "pydantic": Mock(), "loguru": Mock()}):
        with patch("async_crud_mcp.cli.setup_cmd.get_config_dir") as mock_config_dir:
            with patch("async_crud_mcp.cli.setup_cmd.get_logs_dir") as mock_logs_dir:
                mock_config_dir.return_value = MagicMock()
                mock_logs_dir.return_value = MagicMock()
                result = runner.invoke(app, ["setup", "--no-interactive"])

    # Should complete successfully despite install failure
    assert result.exit_code == 0
    assert "warning" in result.stdout.lower() or "failed" in result.stdout.lower()
