"""Tests for daemon subcommand group."""

from unittest.mock import MagicMock, mock_open, patch

from typer.testing import CliRunner

from async_crud_mcp.cli.daemon_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.daemon_cmd.check_health")
def test_status_healthy(mock_check_health):
    """Test status command with healthy daemon."""
    mock_check_health.return_value = {
        "status": "healthy",
        "message": "All systems operational",
        "config_readable": True,
        "daemon_enabled": True,
        "logs_dir_exists": True,
        "port_listening": True,
        "host": "127.0.0.1",
        "port": 8720,
    }

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "healthy" in result.stdout.lower()


@patch("async_crud_mcp.cli.daemon_cmd.check_health")
def test_status_degraded(mock_check_health):
    """Test status command with degraded daemon."""
    mock_check_health.return_value = {
        "status": "degraded",
        "message": "Some issues detected",
        "config_readable": True,
        "daemon_enabled": False,
    }

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "degraded" in result.stdout.lower()


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
def test_logs_not_found(mock_get_logs_dir):
    """Test logs command when log file doesn't exist."""
    mock_path = MagicMock()
    mock_path.__truediv__ = lambda self, other: MagicMock(exists=lambda: False)
    mock_get_logs_dir.return_value = mock_path

    result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
@patch("builtins.open", new_callable=mock_open, read_data="Test log line\n")
def test_logs_display(mock_file, mock_get_logs_dir):
    """Test logs command displays log content."""
    mock_path = MagicMock()
    mock_log_file = MagicMock()
    mock_log_file.exists.return_value = True
    mock_path.__truediv__ = lambda self, other: mock_log_file
    mock_get_logs_dir.return_value = mock_path

    result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
