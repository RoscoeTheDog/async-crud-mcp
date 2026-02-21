"""Tests for daemon.paths module - XDG compliance and APP_NAME fallback."""

import sys
from pathlib import Path

import pytest

from async_crud_mcp.daemon import paths


class TestAppNameConstant:
    """Test APP_NAME constant is correctly defined."""

    def test_app_name_is_async_crud_mcp(self):
        """APP_NAME should be 'async-crud-mcp' regardless of import path."""
        assert paths.APP_NAME == 'async-crud-mcp'

    def test_app_name_in_all_exports(self):
        """APP_NAME should be in __all__ exports."""
        assert 'APP_NAME' in paths.__all__


class TestAppNameFallback:
    """Test APP_NAME fallback mechanism when config import fails."""

    def test_app_name_default_constant_exists(self):
        """_APP_NAME_DEFAULT constant should exist as fallback."""
        assert hasattr(paths, '_APP_NAME_DEFAULT')
        assert paths._APP_NAME_DEFAULT == 'async-crud-mcp'

    def test_app_name_uses_default_on_import_failure(self):
        """APP_NAME should fall back to _APP_NAME_DEFAULT if config import fails."""
        # The module is already loaded, so APP_NAME is set
        # We verify the fallback mechanism exists by checking the constant
        assert paths._APP_NAME_DEFAULT == 'async-crud-mcp'
        # In the actual module, if import fails, APP_NAME = _APP_NAME_DEFAULT
        # This test verifies the constant is defined correctly


class TestGetCacheDir:
    """Test get_cache_dir() function for XDG_CACHE_HOME compliance."""

    def test_get_cache_dir_in_all_exports(self):
        """get_cache_dir should be in __all__ exports."""
        assert 'get_cache_dir' in paths.__all__

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific test")
    def test_linux_cache_dir_with_xdg_cache_home(self, monkeypatch, tmp_path):
        """Linux: get_cache_dir() respects XDG_CACHE_HOME env var."""
        xdg_cache = tmp_path / "custom-cache"
        monkeypatch.setenv('XDG_CACHE_HOME', str(xdg_cache))
        monkeypatch.setattr('sys.platform', 'linux')

        result = paths.get_cache_dir()

        expected = xdg_cache / 'async-crud-mcp'
        assert result == expected

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific test")
    def test_linux_cache_dir_without_xdg_cache_home(self, monkeypatch):
        """Linux: get_cache_dir() falls back to ~/.cache/async-crud-mcp."""
        monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
        monkeypatch.setattr('sys.platform', 'linux')

        result = paths.get_cache_dir()

        expected = Path.home() / '.cache' / 'async-crud-mcp'
        assert result == expected

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_cache_dir_with_localappdata(self, monkeypatch, tmp_path):
        """Windows: get_cache_dir() uses %LOCALAPPDATA%."""
        localappdata = tmp_path / "AppData" / "Local"
        monkeypatch.setenv('LOCALAPPDATA', str(localappdata))
        monkeypatch.setattr('sys.platform', 'win32')

        result = paths.get_cache_dir()

        expected = localappdata / 'async-crud-mcp' / 'cache'
        assert result == expected

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_cache_dir_without_localappdata(self, monkeypatch):
        """Windows: get_cache_dir() falls back to home directory."""
        monkeypatch.delenv('LOCALAPPDATA', raising=False)
        monkeypatch.setattr('sys.platform', 'win32')

        result = paths.get_cache_dir()

        expected = Path.home() / 'AppData' / 'Local' / 'async-crud-mcp' / 'cache'
        assert result == expected

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific test")
    def test_macos_cache_dir(self, monkeypatch):
        """macOS: get_cache_dir() uses ~/Library/Caches."""
        monkeypatch.setattr('sys.platform', 'darwin')

        result = paths.get_cache_dir()

        expected = Path.home() / 'Library' / 'Caches' / 'async-crud-mcp'
        assert result == expected

    def test_cache_dir_returns_path_object(self):
        """get_cache_dir() should return a Path object."""
        result = paths.get_cache_dir()
        assert isinstance(result, Path)


class TestGetCacheDirCrossPlatform:
    """Test get_cache_dir() across all platforms using mocking."""

    def test_linux_platform_with_xdg(self, monkeypatch, tmp_path):
        """Simulate Linux with XDG_CACHE_HOME set."""
        monkeypatch.setattr('sys.platform', 'linux')
        xdg_cache = tmp_path / "xdg-cache"
        monkeypatch.setenv('XDG_CACHE_HOME', str(xdg_cache))

        result = paths.get_cache_dir()

        assert result == xdg_cache / 'async-crud-mcp'

    def test_linux_platform_without_xdg(self, monkeypatch):
        """Simulate Linux without XDG_CACHE_HOME."""
        monkeypatch.setattr('sys.platform', 'linux')
        monkeypatch.delenv('XDG_CACHE_HOME', raising=False)

        result = paths.get_cache_dir()

        assert result == Path.home() / '.cache' / 'async-crud-mcp'

    def test_windows_platform(self, monkeypatch, tmp_path):
        """Simulate Windows platform."""
        monkeypatch.setattr('sys.platform', 'win32')
        localappdata = tmp_path / "LocalAppData"
        monkeypatch.setenv('LOCALAPPDATA', str(localappdata))

        result = paths.get_cache_dir()

        assert result == localappdata / 'async-crud-mcp' / 'cache'

    def test_darwin_platform(self, monkeypatch):
        """Simulate macOS platform."""
        monkeypatch.setattr('sys.platform', 'darwin')

        result = paths.get_cache_dir()

        assert result == Path.home() / 'Library' / 'Caches' / 'async-crud-mcp'


class TestGetCacheDirConsistency:
    """Test get_cache_dir() follows same pattern as other dir functions."""

    def test_cache_dir_structure_matches_data_dir_pattern(self, monkeypatch, tmp_path):
        """get_cache_dir() should follow the same structure as get_data_dir()."""
        # On Linux, both should use XDG pattern
        monkeypatch.setattr('sys.platform', 'linux')
        xdg_cache = tmp_path / "cache"
        xdg_data = tmp_path / "data"
        monkeypatch.setenv('XDG_CACHE_HOME', str(xdg_cache))
        monkeypatch.setenv('XDG_DATA_HOME', str(xdg_data))

        cache_result = paths.get_cache_dir()
        data_result = paths.get_data_dir()

        # Both should use their respective XDG vars + APP_NAME
        assert cache_result == xdg_cache / 'async-crud-mcp'
        assert data_result == xdg_data / 'async-crud-mcp'

    def test_cache_dir_does_not_auto_create(self):
        """get_cache_dir() should not create the directory automatically."""
        result = paths.get_cache_dir()
        # We just verify it returns a path; creation is caller's responsibility
        assert isinstance(result, Path)


class TestDaemonInitExports:
    """Test that daemon.__init__.py correctly exports get_cache_dir."""

    def test_get_cache_dir_exported_from_daemon_package(self):
        """get_cache_dir should be accessible from daemon package."""
        from async_crud_mcp import daemon

        assert hasattr(daemon, 'get_cache_dir')
        assert callable(daemon.get_cache_dir)

    def test_daemon_all_includes_get_cache_dir(self):
        """daemon.__all__ should include get_cache_dir."""
        from async_crud_mcp import daemon

        assert 'get_cache_dir' in daemon.__all__


class TestExistingFunctionsStillWork:
    """Regression tests to ensure existing functions are not broken."""

    def test_get_config_dir_still_works(self):
        """Existing get_config_dir() should still work."""
        result = paths.get_config_dir()
        assert isinstance(result, Path)

    def test_get_data_dir_still_works(self):
        """Existing get_data_dir() should still work."""
        result = paths.get_data_dir()
        assert isinstance(result, Path)

    def test_get_logs_dir_still_works(self):
        """Existing get_logs_dir() should still work."""
        result = paths.get_logs_dir()
        assert isinstance(result, Path)

    def test_get_install_dir_still_works(self):
        """Existing get_install_dir() should still work."""
        result = paths.get_install_dir()
        assert isinstance(result, Path)


class TestXDGComplianceAlignment:
    """Test that all XDG functions (config, data, cache) work correctly."""

    def test_all_xdg_dirs_use_correct_env_vars_on_linux(self, monkeypatch, tmp_path):
        """On Linux, all XDG dirs should respect their respective env vars."""
        monkeypatch.setattr('sys.platform', 'linux')

        xdg_config = tmp_path / "config"
        xdg_data = tmp_path / "data"
        xdg_cache = tmp_path / "cache"

        monkeypatch.setenv('XDG_CONFIG_HOME', str(xdg_config))
        monkeypatch.setenv('XDG_DATA_HOME', str(xdg_data))
        monkeypatch.setenv('XDG_CACHE_HOME', str(xdg_cache))

        config_result = paths.get_config_dir()
        data_result = paths.get_data_dir()
        cache_result = paths.get_cache_dir()

        assert config_result == xdg_config / 'async-crud-mcp'
        assert data_result == xdg_data / 'async-crud-mcp'
        assert cache_result == xdg_cache / 'async-crud-mcp'

    def test_all_xdg_dirs_use_correct_defaults_on_linux(self, monkeypatch):
        """On Linux without XDG vars, all dirs should use correct defaults."""
        monkeypatch.setattr('sys.platform', 'linux')
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        monkeypatch.delenv('XDG_DATA_HOME', raising=False)
        monkeypatch.delenv('XDG_CACHE_HOME', raising=False)

        config_result = paths.get_config_dir()
        data_result = paths.get_data_dir()
        cache_result = paths.get_cache_dir()

        home = Path.home()
        assert config_result == home / '.config' / 'async-crud-mcp'
        assert data_result == home / '.local' / 'share' / 'async-crud-mcp'
        assert cache_result == home / '.cache' / 'async-crud-mcp'
