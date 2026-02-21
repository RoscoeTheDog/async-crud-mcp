"""Tests for scripts/test_server.py."""

import argparse
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open

import pytest


# Import functions from the test_server script
import sys
scripts_dir = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

import test_server


class TestArgumentParsing:
    """Test command-line argument parsing."""

    def test_default_args(self):
        """Test that default arguments are set correctly."""
        with patch('sys.argv', ['test_server.py']):
            parser = argparse.ArgumentParser()
            parser.add_argument('--port', type=int, default=None)
            parser.add_argument('--skip-logs', action='store_true')
            parser.add_argument('--log-age', type=int, default=168)

            args = parser.parse_args([])

            assert args.port is None
            assert args.skip_logs is False
            assert args.log_age == 168

    def test_port_argument(self):
        """Test --port argument parsing."""
        parser = argparse.ArgumentParser()
        parser.add_argument('--port', type=int, default=None)

        args = parser.parse_args(['--port', '9000'])
        assert args.port == 9000

    def test_skip_logs_argument(self):
        """Test --skip-logs argument parsing."""
        parser = argparse.ArgumentParser()
        parser.add_argument('--skip-logs', action='store_true')

        args = parser.parse_args(['--skip-logs'])
        assert args.skip_logs is True

    def test_log_age_argument(self):
        """Test --log-age argument parsing."""
        parser = argparse.ArgumentParser()
        parser.add_argument('--log-age', type=int, default=168)

        args = parser.parse_args(['--log-age', '24'])
        assert args.log_age == 24


class TestGetLogsDirFallback:
    """Test get_logs_dir_fallback function."""

    @patch('test_server.platform.system')
    def test_windows_path_programdata_exists(self, mock_system, tmp_path):
        """Test Windows returns ProgramData logs when that directory exists."""
        mock_system.return_value = 'Windows'
        pd_logs = tmp_path / 'async-crud-mcp' / 'logs'
        pd_logs.mkdir(parents=True)

        with patch.dict('os.environ', {
            'PROGRAMDATA': str(tmp_path),
            'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local',
        }):
            result = test_server.get_logs_dir_fallback()
            assert result == pd_logs

    @patch('test_server.platform.system')
    def test_windows_path_localappdata_fallback(self, mock_system, tmp_path):
        """Test Windows falls back to LOCALAPPDATA when ProgramData logs don't exist."""
        mock_system.return_value = 'Windows'
        # ProgramData dir exists but NOT the logs subdirectory
        with patch.dict('os.environ', {
            'PROGRAMDATA': str(tmp_path),
            'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local',
        }):
            result = test_server.get_logs_dir_fallback()
            expected = Path('C:\\Users\\Test\\AppData\\Local') / 'async-crud-mcp' / 'logs'
            assert result == expected

    @patch('test_server.platform.system')
    def test_darwin_path(self, mock_system):
        """Test macOS logs directory path."""
        mock_system.return_value = 'Darwin'

        result = test_server.get_logs_dir_fallback()
        expected = Path.home() / 'Library' / 'Logs' / 'async-crud-mcp'
        assert result == expected

    @patch('test_server.platform.system')
    def test_linux_path_with_xdg(self, mock_system):
        """Test Linux logs directory path with XDG_STATE_HOME."""
        mock_system.return_value = 'Linux'

        with patch.dict('os.environ', {'XDG_STATE_HOME': '/home/test/.local/state'}):
            result = test_server.get_logs_dir_fallback()
            expected = Path('/home/test/.local/state') / 'async-crud-mcp' / 'logs'
            assert result == expected

    @patch('test_server.Path.home')
    @patch('test_server.platform.system')
    def test_linux_path_without_xdg(self, mock_system, mock_home):
        """Test Linux logs directory path without XDG_STATE_HOME."""
        mock_system.return_value = 'Linux'
        mock_home.return_value = Path('/home/test')

        with patch.dict('os.environ', {}, clear=True):
            result = test_server.get_logs_dir_fallback()
            expected = Path('/home/test') / '.local' / 'state' / 'async-crud-mcp' / 'logs'
            assert result == expected


class TestCheckLogFileAge:
    """Test check_log_file_age function."""

    @patch('test_server.glob.glob')
    @patch('test_server.get_logs_dir_fallback')
    def test_logs_dir_not_found(self, mock_get_logs_dir, mock_glob):
        """Test when logs directory doesn't exist."""
        mock_logs_dir = MagicMock()
        mock_logs_dir.exists.return_value = False
        mock_logs_dir.__str__.return_value = '/path/to/logs'
        mock_get_logs_dir.return_value = mock_logs_dir

        with patch('test_server.print_status'):
            result = test_server.check_log_file_age(168)

        assert result == 'fail'

    @patch('test_server.time.time')
    @patch('test_server.glob.glob')
    @patch('test_server.get_logs_dir_fallback')
    def test_no_log_files_found(self, mock_get_logs_dir, mock_glob, mock_time):
        """Test when no log files are found."""
        mock_logs_dir = MagicMock()
        mock_logs_dir.exists.return_value = True
        mock_logs_dir.__truediv__ = lambda self, other: MagicMock(__str__=lambda x: f'/path/to/logs/{other}')
        mock_get_logs_dir.return_value = mock_logs_dir
        mock_glob.return_value = []

        with patch('test_server.print_status'):
            result = test_server.check_log_file_age(168)

        assert result == 'fail'

    @patch('test_server.time.time')
    @patch('test_server.Path')
    @patch('test_server.glob.glob')
    @patch('test_server.get_logs_dir_fallback')
    def test_log_file_too_old(self, mock_get_logs_dir, mock_glob, mock_path_class, mock_time):
        """Test when newest log file is older than max age."""
        mock_logs_dir = MagicMock()
        mock_logs_dir.exists.return_value = True
        mock_logs_dir.__truediv__ = lambda self, other: MagicMock(__str__=lambda x: f'/path/to/logs/{other}')
        mock_get_logs_dir.return_value = mock_logs_dir

        # Mock log files
        mock_glob.return_value = ['/path/to/logs/old.log']

        # Mock file stat - 200 hours old
        current_time = 1000000
        file_mtime = current_time - (200 * 3600)
        mock_time.return_value = current_time

        mock_stat = MagicMock()
        mock_stat.st_mtime = file_mtime

        mock_path = MagicMock()
        mock_path.stat.return_value = mock_stat
        mock_path.name = 'old.log'
        mock_path_class.return_value = mock_path

        with patch('test_server.print_status'):
            result = test_server.check_log_file_age(168)

        assert result == 'fail'

    @patch('test_server.print_status')
    @patch('test_server.time.time')
    @patch('test_server.Path')
    @patch('test_server.glob.glob')
    @patch('test_server.get_logs_dir_fallback')
    def test_log_file_within_age(self, mock_fallback, mock_glob, mock_path_class, mock_time, mock_print):
        """Test when newest log file is within max age."""
        # Mock fallback dir (also serves as only candidate when imports fail)
        mock_logs_dir = MagicMock()
        mock_logs_dir.exists.return_value = True
        mock_logs_dir.resolve.return_value = Path('/path/to/logs')
        mock_logs_dir.__truediv__ = lambda self, other: MagicMock(
            __str__=lambda x: f'/path/to/logs/{other}',
        )
        mock_fallback.return_value = mock_logs_dir

        # Mock log files
        log_file_path = '/path/to/logs/recent.log'
        mock_glob.return_value = [log_file_path]

        # Mock file stat - 2 hours old
        current_time = 1000000.0
        file_mtime = current_time - (2 * 3600)
        mock_time.return_value = current_time

        # Mock Path instances
        mock_stat = MagicMock()
        mock_stat.st_mtime = file_mtime

        mock_path_instance = MagicMock()
        mock_path_instance.stat.return_value = mock_stat
        mock_path_instance.name = 'recent.log'
        mock_path_class.return_value = mock_path_instance

        result = test_server.check_log_file_age(168)

        assert result == 'pass'

    @patch('test_server.print_status')
    @patch('test_server.time.time')
    @patch('test_server.Path')
    @patch('test_server.glob.glob')
    @patch('test_server.get_logs_dir_fallback')
    def test_multiple_log_files_finds_newest(self, mock_fallback, mock_glob, mock_path_class, mock_time, mock_print):
        """Test that the newest log file is correctly identified."""
        # Mock fallback dir
        mock_logs_dir = MagicMock()
        mock_logs_dir.exists.return_value = True
        mock_logs_dir.resolve.return_value = Path('/path/to/logs')
        mock_logs_dir.__truediv__ = lambda self, other: MagicMock(
            __str__=lambda x: f'/path/to/logs/{other}',
        )
        mock_fallback.return_value = mock_logs_dir

        # Mock multiple log files
        mock_glob.return_value = ['/path/to/logs/old.log', '/path/to/logs/newer.log']

        current_time = 1000000.0
        mock_time.return_value = current_time

        # Create side effect function for Path
        def path_side_effect(filepath):
            mock_path = MagicMock()
            mock_stat = MagicMock()

            if 'old.log' in str(filepath):
                mock_stat.st_mtime = current_time - (10 * 3600)  # 10 hours old
                mock_path.name = 'old.log'
            else:
                mock_stat.st_mtime = current_time - (2 * 3600)   # 2 hours old (newest)
                mock_path.name = 'newer.log'

            mock_path.stat.return_value = mock_stat
            return mock_path

        mock_path_class.side_effect = path_side_effect

        result = test_server.check_log_file_age(168)

        assert result == 'pass'


class TestCheckServerConnectivity:
    """Test check_server_connectivity function."""

    @patch('test_server.urlopen')
    @patch('test_server.get_config_paths')
    def test_port_override(self, mock_get_config_paths, mock_urlopen):
        """Test that port_override is used instead of config port."""
        # Mock config file exists with port 8765
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = True
        mock_get_config_paths.return_value = mock_config_path

        config_data = json.dumps({"daemon": {"host": "127.0.0.1", "port": 8720}})

        with patch('builtins.open', mock_open(read_data=config_data)):
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)
            mock_urlopen.return_value = mock_response

            with patch('test_server.print_status'):
                result = test_server.check_server_connectivity(port_override=9000)

            # Verify the URL used was with port 9000, not 8765
            call_args = mock_urlopen.call_args[0][0]
            assert '9000' in str(call_args.full_url)
            assert result == 'pass'

    @patch('test_server.urlopen')
    @patch('test_server.get_config_paths')
    def test_no_port_override_uses_config(self, mock_get_config_paths, mock_urlopen):
        """Test that config port is used when no override."""
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = True
        mock_get_config_paths.return_value = mock_config_path

        config_data = json.dumps({"daemon": {"host": "127.0.0.1", "port": 7777}})

        with patch('builtins.open', mock_open(read_data=config_data)):
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)
            mock_urlopen.return_value = mock_response

            with patch('test_server.print_status'):
                result = test_server.check_server_connectivity(port_override=None)

            call_args = mock_urlopen.call_args[0][0]
            assert '7777' in str(call_args.full_url)
            assert result == 'pass'


class TestPrintStatus:
    """Test print_status function."""

    @patch('builtins.print')
    def test_pass_status(self, mock_print):
        """Test PASS status output."""
        test_server.print_status("Test Check", 'pass', "Test message")

        calls = [str(call) for call in mock_print.call_args_list]
        output = ''.join(calls)
        assert 'PASS' in output
        assert 'Test Check' in output

    @patch('builtins.print')
    def test_fail_status(self, mock_print):
        """Test FAIL status output."""
        test_server.print_status("Test Check", 'fail', "Test message")

        calls = [str(call) for call in mock_print.call_args_list]
        output = ''.join(calls)
        assert 'FAIL' in output
        assert 'Test Check' in output

    @patch('builtins.print')
    def test_skip_status(self, mock_print):
        """Test SKIP status output."""
        test_server.print_status("Test Check", 'skip', "Test message")

        calls = [str(call) for call in mock_print.call_args_list]
        output = ''.join(calls)
        assert 'SKIP' in output
        assert 'Test Check' in output


class TestMainFunction:
    """Test main function integration."""

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py', '--skip-logs'])
    def test_skip_logs_flag(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                           mock_server, mock_log_age):
        """Test that --skip-logs flag skips log age check."""
        # Set all checks to pass
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'pass'
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'

        with patch('builtins.print'):
            exit_code = test_server.main()

        # Log age check should NOT be called
        mock_log_age.assert_not_called()
        assert exit_code == 0

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py', '--log-age', '24'])
    def test_log_age_custom_value(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                                   mock_server, mock_log_age):
        """Test that --log-age passes custom value."""
        # Set all checks to pass
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'pass'
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'
        mock_log_age.return_value = 'pass'

        with patch('builtins.print'):
            exit_code = test_server.main()

        # Log age check should be called with 24
        mock_log_age.assert_called_once_with(24)
        assert exit_code == 0

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py', '--port', '9999'])
    def test_port_override_passed(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                                   mock_server, mock_log_age):
        """Test that --port is passed to check_server_connectivity."""
        # Set all checks to pass
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'pass'
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'
        mock_log_age.return_value = 'pass'

        with patch('builtins.print'):
            exit_code = test_server.main()

        # Server check should be called with port_override=9999
        mock_server.assert_called_once_with(port_override=9999)
        assert exit_code == 0

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py'])
    def test_overall_fail_on_any_failure(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                                          mock_server, mock_log_age):
        """Test that OVERALL: FAIL is returned when any check fails."""
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'fail'  # One failure
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'
        mock_log_age.return_value = 'pass'

        with patch('builtins.print'):
            exit_code = test_server.main()

        assert exit_code == 1

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py'])
    def test_overall_pass_all_checks(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                                      mock_server, mock_log_age):
        """Test that OVERALL: PASS is returned when all checks pass."""
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'pass'
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'
        mock_log_age.return_value = 'pass'

        with patch('builtins.print'):
            exit_code = test_server.main()

        assert exit_code == 0

    @patch('test_server.check_log_file_age')
    @patch('test_server.check_server_connectivity')
    @patch('test_server.check_daemon_service')
    @patch('test_server.check_config_file')
    @patch('test_server.check_package_import')
    @patch('test_server.check_python_version')
    @patch('sys.argv', ['test_server.py', '--skip-logs'])
    def test_overall_pass_with_skip(self, mock_py_ver, mock_pkg, mock_cfg, mock_daemon,
                                     mock_server, mock_log_age):
        """Test that OVERALL: PASS when some checks are skipped."""
        mock_py_ver.return_value = 'pass'
        mock_pkg.return_value = 'pass'
        mock_cfg.return_value = 'pass'
        mock_daemon.return_value = 'pass'
        mock_server.return_value = 'pass'
        # Log age is skipped, not called

        with patch('builtins.print'):
            exit_code = test_server.main()

        assert exit_code == 0
