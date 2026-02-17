"""Tests for daemon subcommand group."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from typer.testing import CliRunner

from async_crud_mcp.cli.daemon_cmd import app

runner = CliRunner()


@patch("async_crud_mcp.cli.daemon_cmd.atomic_write_config")
@patch("async_crud_mcp.cli.daemon_cmd.get_config_file_path")
def test_start_mutates_config(mock_get_config_file_path, mock_atomic_write):
    """Test start command mutates config to enable daemon."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = True
    mock_config_path.read_text.return_value = json.dumps({
        "daemon": {"enabled": False, "port": 8720}
    })
    mock_get_config_file_path.return_value = mock_config_path

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_atomic_write.assert_called_once()
    written_config = mock_atomic_write.call_args[0][1]
    assert written_config["daemon"]["enabled"] is True


@patch("async_crud_mcp.cli.daemon_cmd.generate_default_config")
@patch("async_crud_mcp.cli.daemon_cmd.atomic_write_config")
@patch("async_crud_mcp.cli.daemon_cmd.get_config_file_path")
def test_start_creates_config_if_missing(mock_get_config_file_path, mock_atomic_write, mock_generate_default):
    """Test start command creates config if it doesn't exist."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = False
    mock_config_path.parent = MagicMock()
    mock_get_config_file_path.return_value = mock_config_path
    mock_generate_default.return_value = {"daemon": {"enabled": False}}

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_generate_default.assert_called_once()
    mock_atomic_write.assert_called_once()
    written_config = mock_atomic_write.call_args[0][1]
    assert written_config["daemon"]["enabled"] is True


@patch("async_crud_mcp.cli.daemon_cmd.atomic_write_config")
@patch("async_crud_mcp.cli.daemon_cmd.get_config_file_path")
def test_stop_mutates_config(mock_get_config_file_path, mock_atomic_write):
    """Test stop command mutates config to disable daemon."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = True
    mock_config_path.read_text.return_value = json.dumps({
        "daemon": {"enabled": True, "port": 8720}
    })
    mock_get_config_file_path.return_value = mock_config_path

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    mock_atomic_write.assert_called_once()
    written_config = mock_atomic_write.call_args[0][1]
    assert written_config["daemon"]["enabled"] is False


@patch("async_crud_mcp.cli.daemon_cmd.get_config_file_path")
def test_stop_no_config_exits(mock_get_config_file_path):
    """Test stop command exits with code 1 when config doesn't exist."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = False
    mock_get_config_file_path.return_value = mock_config_path

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


@patch("async_crud_mcp.cli.daemon_cmd.time.sleep")
@patch("async_crud_mcp.cli.daemon_cmd.atomic_write_config")
@patch("async_crud_mcp.cli.daemon_cmd.get_config_file_path")
def test_restart_cycles_enabled(mock_get_config_file_path, mock_atomic_write, mock_sleep):
    """Test restart command cycles enabled flag with wait."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = True
    mock_config_path.read_text.return_value = json.dumps({
        "daemon": {
            "enabled": True,
            "port": 8720,
            "config_poll_seconds": 3,
            "config_debounce_seconds": 1.0
        }
    })
    mock_get_config_file_path.return_value = mock_config_path

    result = runner.invoke(app, ["restart"])

    assert result.exit_code == 0
    assert mock_atomic_write.call_count == 2

    first_call_config = mock_atomic_write.call_args_list[0][0][1]
    assert first_call_config["daemon"]["enabled"] is False

    second_call_config = mock_atomic_write.call_args_list[1][0][1]
    assert second_call_config["daemon"]["enabled"] is True

    mock_sleep.assert_called_once_with(4.0)


@patch("async_crud_mcp.cli.daemon_cmd.check_health")
def test_status_json_output(mock_check_health):
    """Test status command with JSON output."""
    health_data = {
        "status": "healthy",
        "message": "OK",
        "config_readable": True,
        "daemon_enabled": True,
    }
    mock_check_health.return_value = health_data

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    output_data = json.loads(result.stdout)
    assert output_data == health_data


@patch("async_crud_mcp.cli.daemon_cmd.get_user_config_file_path")
def test_status_username(mock_get_user_config_file_path):
    """Test status command with --username option."""
    mock_config_path = MagicMock(spec=Path)
    mock_config_path.exists.return_value = True
    mock_config_path.read_text.return_value = json.dumps({
        "daemon": {"enabled": True, "host": "127.0.0.1", "port": 8721}
    })
    mock_get_user_config_file_path.return_value = mock_config_path

    with patch("socket.socket") as mock_socket:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_socket.return_value = mock_sock

        result = runner.invoke(app, ["status", "--username", "testuser"])

        assert result.exit_code == 0
        mock_get_user_config_file_path.assert_called_once_with("testuser")


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
@patch("builtins.open", new_callable=mock_open, read_data="".join([f"Line {i}\n" for i in range(100)]))
def test_logs_lines(mock_file, mock_get_logs_dir):
    """Test logs command with --lines option."""
    mock_path = MagicMock()
    mock_log_file = MagicMock()
    mock_log_file.exists.return_value = True
    mock_path.__truediv__ = lambda self, other: mock_log_file
    mock_get_logs_dir.return_value = mock_path

    result = runner.invoke(app, ["logs", "--lines", "10"])

    assert result.exit_code == 0


@patch("async_crud_mcp.cli.daemon_cmd.get_user_logs_dir")
@patch("builtins.open", new_callable=mock_open, read_data="User log content\n")
def test_logs_username(mock_file, mock_get_user_logs_dir):
    """Test logs command with --username option."""
    mock_path = MagicMock()
    mock_log_file = MagicMock()
    mock_log_file.exists.return_value = True
    mock_path.__truediv__ = lambda self, other: mock_log_file
    mock_get_user_logs_dir.return_value = mock_path

    result = runner.invoke(app, ["logs", "--username", "testuser"])

    assert result.exit_code == 0
    mock_get_user_logs_dir.assert_called_once_with("testuser")


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


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
@patch("builtins.open", new_callable=mock_open, read_data="Service log content\n")
def test_logs_programdata_fallback_on_windows(mock_file, mock_get_logs_dir):
    """Test logs command falls back to ProgramData path on Windows when primary log is missing."""
    from pathlib import Path
    from unittest.mock import call

    primary_mock = MagicMock(spec=Path)
    primary_mock.exists.return_value = False

    fallback_mock = MagicMock(spec=Path)
    fallback_mock.exists.return_value = True

    mock_path = MagicMock()
    mock_path.__truediv__ = lambda self, other: primary_mock
    mock_get_logs_dir.return_value = mock_path

    with patch("async_crud_mcp.cli.daemon_cmd.sys") as mock_sys, \
         patch("async_crud_mcp.cli.daemon_cmd.os") as mock_os, \
         patch("async_crud_mcp.cli.daemon_cmd.Path") as mock_path_cls:
        mock_sys.platform = "win32"
        mock_os.environ.get.return_value = "C:\\ProgramData"
        mock_path_cls.return_value.__truediv__ = lambda self, other: mock_path_cls.return_value
        mock_path_cls.return_value.exists.return_value = True

        result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
    mock_os.environ.get.assert_called_once_with("PROGRAMDATA", "C:\\ProgramData")


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
def test_logs_no_fallback_on_non_windows(mock_get_logs_dir):
    """Test logs command does not attempt ProgramData fallback on non-Windows."""
    mock_path = MagicMock()
    primary_mock = MagicMock()
    primary_mock.exists.return_value = False
    mock_path.__truediv__ = lambda self, other: primary_mock
    mock_get_logs_dir.return_value = mock_path

    with patch("async_crud_mcp.cli.daemon_cmd.sys") as mock_sys, \
         patch("async_crud_mcp.cli.daemon_cmd.os") as mock_os:
        mock_sys.platform = "linux"

        result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()
    mock_os.environ.get.assert_not_called()


@patch("async_crud_mcp.cli.daemon_cmd.get_logs_dir")
def test_logs_programdata_fallback_not_found(mock_get_logs_dir):
    """Test logs command shows 'not found' when both primary and ProgramData paths are missing."""
    mock_path = MagicMock()
    primary_mock = MagicMock()
    primary_mock.exists.return_value = False
    mock_path.__truediv__ = lambda self, other: primary_mock
    mock_get_logs_dir.return_value = mock_path

    with patch("async_crud_mcp.cli.daemon_cmd.sys") as mock_sys, \
         patch("async_crud_mcp.cli.daemon_cmd.os") as mock_os, \
         patch("async_crud_mcp.cli.daemon_cmd.Path") as mock_path_cls:
        mock_sys.platform = "win32"
        mock_os.environ.get.return_value = "C:\\ProgramData"
        fallback_mock = MagicMock()
        fallback_mock.exists.return_value = False
        mock_path_cls.return_value.__truediv__ = lambda self, other: mock_path_cls.return_value
        mock_path_cls.return_value.exists.return_value = False

        result = runner.invoke(app, ["logs"])

    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()
