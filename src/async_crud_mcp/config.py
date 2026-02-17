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

from pydantic import BaseModel, Field, field_validator
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
    port: int | None = Field(default=8720, ge=1024, le=65535)  # None = auto-assign via username hash
    transport: Literal["sse", "stdio"] = "sse"
    log_level: str = "DEBUG"
    config_poll_seconds: int = 3
    config_debounce_seconds: float = 1.0
    session_poll_seconds: int = 3
    wait_for_session: bool = True
    health_check_interval: int = 30

    @field_validator('host')
    @classmethod
    def host_must_not_be_empty(cls, v: str) -> str:
        """Validate that host is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError('host must be a non-empty string')
        return v


class PathRule(BaseModel):
    """A single access control rule for path-based operation restrictions.

    Rules are evaluated in priority order (highest first, first-match-wins).
    """

    path: str = Field(..., description="Path prefix to match against (resolved relative to cwd)")
    operations: list[str] = Field(
        ...,
        description='Operation types this rule applies to: "write", "update", "delete", "rename", or "*" for all',
    )
    action: Literal["allow", "deny"] = Field(..., description="Whether to allow or deny the operation")
    priority: int = Field(default=0, description="Rule priority (higher = evaluated first)")


class CrudConfig(BaseModel):
    """CRUD operations configuration section."""

    base_directories: list[str] = Field(default_factory=list)  # List of absolute paths
    default_timeout: float = 30.0
    max_timeout: float = 300.0
    default_encoding: str = "utf-8"
    diff_context_lines: int = 3
    max_file_size_bytes: int = 10_485_760  # 10MB
    access_rules: list[PathRule] = Field(default_factory=list)
    access_policy_file: str | None = None
    default_destructive_policy: Literal["allow", "deny"] = "allow"


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


# Module-level variables
_json_config_file: Path | None = None  # For settings_customise_sources
_settings_cache: "Settings | None" = None  # For singleton pattern


def _strip_comment_fields(data: Any) -> Any:
    """Recursively strip keys starting with _ or $ from dict.

    Args:
        data: Dictionary to clean (or any other type, which is returned as-is)

    Returns:
        Dictionary with comment fields removed, or original value if not a dict
    """
    if not isinstance(data, dict):
        return data
    return {
        k: _strip_comment_fields(v) if isinstance(v, dict) else v
        for k, v in data.items()
        if not k.startswith('_') and not k.startswith('$')
    }


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
    def from_file(cls, config_path: Path | str) -> "Settings":
        """Load settings from a JSON config file.

        Args:
            config_path: Path to JSON config file

        Returns:
            Settings instance loaded from file, or default Settings if file doesn't exist
        """
        path = Path(config_path)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding='utf-8'))
        cleaned = _strip_comment_fields(raw)
        return cls(**cleaned)

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


def get_settings(config_path: Path | str | None = None, *, _force_reload: bool = False) -> Settings:
    """Load settings from optional JSON config file and environment variables.

    Implements singleton pattern - returns cached settings unless _force_reload=True
    or config_path is provided.

    Args:
        config_path: Optional path to JSON config file. If provided, bypasses cache.
        _force_reload: If True, bypasses cache and creates fresh Settings instance

    Returns:
        Settings instance with merged configuration
    """
    global _json_config_file, _settings_cache

    # Return cached settings if available and no reload requested
    if _settings_cache is not None and not _force_reload and config_path is None:
        return _settings_cache

    # Create new settings instance
    if config_path:
        _json_config_file = Path(config_path)
        try:
            settings = Settings()
        finally:
            _json_config_file = None  # Reset after use
    else:
        settings = Settings()

    # Load and merge external access policy file if configured
    if settings.crud.access_policy_file:
        policy_path = Path(settings.crud.access_policy_file)
        if not policy_path.is_absolute():
            policy_path = Path.cwd() / policy_path
        if policy_path.exists():
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            cleaned = _strip_comment_fields(raw)
            policy_rules = [PathRule(**r) for r in cleaned.get("access_rules", [])]
            policy_default = cleaned.get(
                "default_destructive_policy",
                settings.crud.default_destructive_policy,
            )
            # Merge: policy file rules extend (not replace) any rules from env/config
            merged_rules = list(settings.crud.access_rules) + policy_rules
            settings.crud = settings.crud.model_copy(
                update={
                    "access_rules": merged_rules,
                    "default_destructive_policy": policy_default,
                }
            )

    # Cache the settings if no config_path was provided
    if config_path is None:
        _settings_cache = settings

    return settings
