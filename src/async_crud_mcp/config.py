"""Configuration management for async-crud-mcp using pydantic-settings.

Supports hierarchical configuration from:
1. Environment variables (highest priority)
2. JSON config file
3. Default values (lowest priority)

Environment variables use the format: ASYNC_CRUD_MCP_<SECTION>__<FIELD>
Example: ASYNC_CRUD_MCP_DAEMON__PORT=8720
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


# Single app-level constant per PRD 13.6
APP_NAME = "async-crud-mcp"


class JsonConfigSettingsSource(PydanticBaseSettingsSource):
    """Custom settings source for loading from JSON file."""

    def __init__(self, settings_cls: type[BaseSettings], json_file: Path):
        super().__init__(settings_cls)
        self.json_file = json_file

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        """Get field value - required by base class but not used in v2."""
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        """Load configuration from JSON file."""
        if self.json_file.exists():
            with open(self.json_file, encoding="utf-8") as f:
                return json.load(f)
        return {}


class DaemonConfig(BaseModel):
    """Daemon service configuration section."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int | None = 8720  # None = auto-assign via username hash
    transport: Literal["sse", "stdio"] = "sse"
    log_level: str = "DEBUG"
    config_poll_seconds: int = 3
    config_debounce_seconds: float = 1.0
    session_poll_seconds: int = 3
    wait_for_session: bool = True
    health_check_interval: int = 30


class CrudConfig(BaseModel):
    """CRUD operations configuration section."""

    base_directories: list[str] = Field(default_factory=list)  # List of absolute paths
    default_timeout: float = 30.0
    max_timeout: float = 300.0
    default_encoding: str = "utf-8"
    diff_context_lines: int = 3
    max_file_size_bytes: int = 10_485_760  # 10MB


class PersistenceConfig(BaseModel):
    """Persistence layer configuration section."""

    enabled: bool = False
    state_file: str | None = None  # None = default DATA_DIR location
    write_debounce_seconds: float = 1.0
    ttl_multiplier: float = 2.0


class WatcherConfig(BaseModel):
    """File watcher configuration section."""

    enabled: bool = True
    debounce_ms: int = 100


# Module-level variable to store JSON file path for settings_customise_sources
_json_config_file: Path | None = None


class Settings(BaseSettings):
    """Root configuration model with nested sections.

    Loads configuration from (in priority order):
    1. Environment variables with ASYNC_CRUD_MCP_ prefix
    2. JSON config file (if provided)
    3. Default values
    """

    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    crud: CrudConfig = Field(default_factory=CrudConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)

    model_config = SettingsConfigDict(
        env_prefix="ASYNC_CRUD_MCP_",
        env_nested_delimiter="__",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources to add JSON config file support.

        Priority order (highest to lowest):
        1. Environment variables
        2. JSON config file (if _json_config_file module variable is set)
        3. Default values
        """
        global _json_config_file
        if _json_config_file is not None:
            json_source = JsonConfigSettingsSource(settings_cls, json_file=_json_config_file)
            return (env_settings, json_source, init_settings)
        return (env_settings, init_settings)


def get_settings(config_path: Path | str | None = None) -> Settings:
    """Load settings from optional JSON config file and environment variables.

    Args:
        config_path: Optional path to JSON config file

    Returns:
        Settings instance with merged configuration
    """
    global _json_config_file
    if config_path:
        _json_config_file = Path(config_path)
        try:
            settings = Settings()
        finally:
            _json_config_file = None  # Reset after use
        return settings
    return Settings()
