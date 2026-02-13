"""Unit tests for configuration management."""

import json
from pathlib import Path

import pytest

from async_crud_mcp.config import (
    APP_NAME,
    CrudConfig,
    DaemonConfig,
    PersistenceConfig,
    Settings,
    WatcherConfig,
    get_settings,
)


def test_app_name_constant():
    """Test APP_NAME constant is defined correctly."""
    assert APP_NAME == "async-crud-mcp"


def test_default_values():
    """Test all default values match PRD Section 5."""
    settings = Settings()

    # Daemon defaults
    assert settings.daemon.enabled is True
    assert settings.daemon.host == "127.0.0.1"
    assert settings.daemon.port == 8720
    assert settings.daemon.transport == "sse"
    assert settings.daemon.log_level == "DEBUG"
    assert settings.daemon.config_poll_seconds == 3
    assert settings.daemon.config_debounce_seconds == 1.0
    assert settings.daemon.session_poll_seconds == 3
    assert settings.daemon.wait_for_session is True
    assert settings.daemon.health_check_interval == 30

    # CRUD defaults
    assert settings.crud.base_directories == []
    assert settings.crud.default_timeout == 30.0
    assert settings.crud.max_timeout == 300.0
    assert settings.crud.default_encoding == "utf-8"
    assert settings.crud.diff_context_lines == 3
    assert settings.crud.max_file_size_bytes == 10_485_760

    # Persistence defaults
    assert settings.persistence.enabled is False
    assert settings.persistence.state_file is None
    assert settings.persistence.write_debounce_seconds == 1.0
    assert settings.persistence.ttl_multiplier == 2.0

    # Watcher defaults
    assert settings.watcher.enabled is True
    assert settings.watcher.debounce_ms == 100


def test_daemon_section_fields():
    """Test DaemonConfig has all expected fields."""
    daemon = DaemonConfig()
    assert hasattr(daemon, "enabled")
    assert hasattr(daemon, "host")
    assert hasattr(daemon, "port")
    assert hasattr(daemon, "transport")
    assert hasattr(daemon, "log_level")
    assert hasattr(daemon, "config_poll_seconds")
    assert hasattr(daemon, "config_debounce_seconds")
    assert hasattr(daemon, "session_poll_seconds")
    assert hasattr(daemon, "wait_for_session")
    assert hasattr(daemon, "health_check_interval")


def test_crud_section_fields():
    """Test CrudConfig has all expected fields."""
    crud = CrudConfig()
    assert hasattr(crud, "base_directories")
    assert hasattr(crud, "default_timeout")
    assert hasattr(crud, "max_timeout")
    assert hasattr(crud, "default_encoding")
    assert hasattr(crud, "diff_context_lines")
    assert hasattr(crud, "max_file_size_bytes")


def test_persistence_section_fields():
    """Test PersistenceConfig has all expected fields."""
    persistence = PersistenceConfig()
    assert hasattr(persistence, "enabled")
    assert hasattr(persistence, "state_file")
    assert hasattr(persistence, "write_debounce_seconds")
    assert hasattr(persistence, "ttl_multiplier")


def test_watcher_section_fields():
    """Test WatcherConfig has all expected fields."""
    watcher = WatcherConfig()
    assert hasattr(watcher, "enabled")
    assert hasattr(watcher, "debounce_ms")


def test_settings_sections_exist():
    """Test root Settings has daemon, crud, persistence, watcher attributes."""
    settings = Settings()
    assert hasattr(settings, "daemon")
    assert hasattr(settings, "crud")
    assert hasattr(settings, "persistence")
    assert hasattr(settings, "watcher")
    assert isinstance(settings.daemon, DaemonConfig)
    assert isinstance(settings.crud, CrudConfig)
    assert isinstance(settings.persistence, PersistenceConfig)
    assert isinstance(settings.watcher, WatcherConfig)


def test_env_var_override(monkeypatch):
    """Test environment variable override for simple field."""
    monkeypatch.setenv("ASYNC_CRUD_MCP_DAEMON__PORT", "9999")
    settings = Settings()
    assert settings.daemon.port == 9999


def test_nested_env_var_override(monkeypatch):
    """Test environment variable override for nested field."""
    monkeypatch.setenv("ASYNC_CRUD_MCP_CRUD__DEFAULT_TIMEOUT", "60.0")
    settings = Settings()
    assert settings.crud.default_timeout == 60.0


def test_multiple_env_var_overrides(monkeypatch):
    """Test multiple environment variable overrides across sections."""
    monkeypatch.setenv("ASYNC_CRUD_MCP_DAEMON__HOST", "0.0.0.0")
    monkeypatch.setenv("ASYNC_CRUD_MCP_DAEMON__PORT", "7777")
    monkeypatch.setenv("ASYNC_CRUD_MCP_PERSISTENCE__ENABLED", "true")
    monkeypatch.setenv("ASYNC_CRUD_MCP_WATCHER__DEBOUNCE_MS", "200")

    settings = Settings()
    assert settings.daemon.host == "0.0.0.0"
    assert settings.daemon.port == 7777
    assert settings.persistence.enabled is True
    assert settings.watcher.debounce_ms == 200


def test_json_config_loading(tmp_path):
    """Test JSON config file loading with full config."""
    config_file = tmp_path / "config.json"
    config_data = {
        "daemon": {
            "enabled": False,
            "host": "192.168.1.1",
            "port": 5000,
            "transport": "stdio",
            "log_level": "INFO",
        },
        "crud": {
            "base_directories": ["/path/one", "/path/two"],
            "default_timeout": 45.0,
            "max_timeout": 600.0,
        },
        "persistence": {
            "enabled": True,
            "state_file": "/custom/state.json",
        },
        "watcher": {
            "enabled": False,
            "debounce_ms": 500,
        },
    }

    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    settings = get_settings(config_file)

    # Verify daemon section
    assert settings.daemon.enabled is False
    assert settings.daemon.host == "192.168.1.1"
    assert settings.daemon.port == 5000
    assert settings.daemon.transport == "stdio"
    assert settings.daemon.log_level == "INFO"

    # Verify crud section
    assert settings.crud.base_directories == ["/path/one", "/path/two"]
    assert settings.crud.default_timeout == 45.0
    assert settings.crud.max_timeout == 600.0

    # Verify persistence section
    assert settings.persistence.enabled is True
    assert settings.persistence.state_file == "/custom/state.json"

    # Verify watcher section
    assert settings.watcher.enabled is False
    assert settings.watcher.debounce_ms == 500


def test_json_config_partial_override(tmp_path):
    """Test JSON config file with partial config merges with defaults."""
    config_file = tmp_path / "config.json"
    config_data = {
        "daemon": {
            "port": 3000,
        },
        "crud": {
            "default_timeout": 120.0,
        },
    }

    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    settings = get_settings(config_file)

    # Overridden values
    assert settings.daemon.port == 3000
    assert settings.crud.default_timeout == 120.0

    # Default values preserved
    assert settings.daemon.host == "127.0.0.1"
    assert settings.daemon.transport == "sse"
    assert settings.crud.max_timeout == 300.0
    assert settings.persistence.enabled is False
    assert settings.watcher.enabled is True


def test_env_var_overrides_json_config(tmp_path, monkeypatch):
    """Test environment variables have priority over JSON config."""
    config_file = tmp_path / "config.json"
    config_data = {
        "daemon": {
            "port": 3000,
        },
    }

    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setenv("ASYNC_CRUD_MCP_DAEMON__PORT", "4000")

    settings = get_settings(config_file)

    # Environment variable should override JSON
    assert settings.daemon.port == 4000


def test_get_settings_without_config_file():
    """Test get_settings() without config file returns defaults."""
    settings = get_settings()
    assert settings.daemon.port == 8720
    assert settings.crud.default_timeout == 30.0


def test_json_config_nonexistent_file(tmp_path):
    """Test loading config from nonexistent JSON file uses defaults."""
    nonexistent_file = tmp_path / "nonexistent.json"
    settings = get_settings(nonexistent_file)

    # Should use all defaults since file doesn't exist
    assert settings.daemon.port == 8720
    assert settings.daemon.host == "127.0.0.1"
    assert settings.crud.default_timeout == 30.0


def test_daemon_port_none_allowed():
    """Test daemon port can be set to None for auto-assignment."""
    settings = Settings()
    settings.daemon.port = None
    assert settings.daemon.port is None


def test_transport_literal_validation():
    """Test transport field only accepts 'sse' or 'stdio'."""
    daemon = DaemonConfig(transport="sse")
    assert daemon.transport == "sse"

    daemon = DaemonConfig(transport="stdio")
    assert daemon.transport == "stdio"

    # Invalid value should raise validation error
    with pytest.raises(Exception):  # Pydantic ValidationError
        DaemonConfig(transport="invalid")


def test_list_field_default_factory():
    """Test base_directories uses default_factory for list."""
    settings1 = Settings()
    settings2 = Settings()

    # Should be different list instances
    assert settings1.crud.base_directories is not settings2.crud.base_directories

    # Modifying one shouldn't affect the other
    settings1.crud.base_directories.append("/test")
    assert len(settings1.crud.base_directories) == 1
    assert len(settings2.crud.base_directories) == 0
