"""Configuration initialization helper.

Provides config file generation with defaults and optional interactive prompts.
Includes service-context detection for Windows (LocalSystem) where LOCALAPPDATA
points to systemprofile instead of the real user's directory.

Note: For new code, prefer importing path helpers from the ``paths`` module:
    from .paths import get_config_dir, get_logs_dir, get_config_file_path

The inline path helpers in this module are kept for backward compatibility
and standalone usage (e.g., from scripts that import config_init directly).

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name (e.g., my-mcp-server)
    8720  - Default port number
    async_crud_mcp  - Python package name (e.g., my_mcp_server)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Try typer for interactive prompts, fall back to input()
try:
    import typer

    HAS_TYPER = True
except ImportError:
    HAS_TYPER = False

# Configuration - Single APP_NAME convention (ADR-009)
DEFAULT_PORT = 8720
APP_NAME = 'async-crud-mcp'


def _is_windows_service_context() -> bool:
    """Detect if running under Windows service (LocalSystem) context.

    When a Windows service runs as LocalSystem, LOCALAPPDATA points to
    ``C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local``
    which is not a real user directory. This function detects that case
    so callers can fall back to ProgramData.

    Returns:
        True if running under LocalSystem service context.
    """
    if sys.platform != "win32":
        return False
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    return "systemprofile" in local_app_data.lower()


def _get_programdata_dir() -> Path:
    """Get the ProgramData directory for the application.

    Used as a fallback when running in Windows service (LocalSystem) context
    where LOCALAPPDATA points to systemprofile.

    Returns:
        Path to ``C:\\ProgramData\\async-crud-mcp`` (or equivalent).
    """
    program_data = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))
    return program_data / APP_NAME


def get_config_dir(username: str | None = None) -> Path:
    """Get platform-specific config directory.

    On Windows, detects service context (LocalSystem) and falls back to
    ProgramData instead of LOCALAPPDATA/systemprofile.

    Args:
        username: Optional username for multi-user scenarios.

    Returns:
        Path to config directory.
    """
    if sys.platform == "win32":
        if _is_windows_service_context():
            return _get_programdata_dir() / "config"
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME / "config"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        # Linux - XDG
        xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg_config) / APP_NAME.lower()


def get_config_file_path(username: str | None = None) -> Path:
    """Get path to config file.

    Args:
        username: Optional username for multi-user scenarios.

    Returns:
        Path to config.json file.
    """
    return get_config_dir(username) / "config.json"


def get_logs_dir(username: str | None = None) -> Path:
    """Get platform-specific logs directory.

    On Windows, detects service context (LocalSystem) and falls back to
    ProgramData instead of LOCALAPPDATA/systemprofile.

    Args:
        username: Optional username for multi-user scenarios.

    Returns:
        Path to logs directory.
    """
    if sys.platform == "win32":
        if _is_windows_service_context():
            return _get_programdata_dir() / "logs"
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME / "logs"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    else:
        # Linux - XDG
        xdg_state = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
        return Path(xdg_state) / APP_NAME.lower() / "logs"


def get_user_logs_dir(username: str) -> Path:
    """Get per-user logs directory for dispatcher (Windows service context).

    Used by the Multi-User Dispatcher to create per-user log directories
    under ProgramData when running as LocalSystem.

    Args:
        username: OS username.

    Returns:
        Path to per-user logs directory (e.g., C:\\ProgramData\\[APP]\\logs\\alice).
    """
    if sys.platform == "win32" and _is_windows_service_context():
        return _get_programdata_dir() / "logs" / username.lower()
    # Outside service context, per-user logs go under the standard logs dir
    return get_logs_dir() / username.lower()


def get_user_config_file_path(username: str) -> Path:
    """Get config file path for a specific user (Windows multi-user).

    Used by the Multi-User Dispatcher to locate per-user configs.
    On Windows, resolves the user's profile directory via registry.

    Args:
        username: OS username.

    Returns:
        Path to user's config.json.
    """
    if sys.platform == "win32":
        try:
            profile_path = _get_user_profile_path(username)
            return profile_path / "AppData" / "Local" / APP_NAME / "config" / "config.json"
        except (ImportError, OSError):
            # Fallback: assume standard path layout
            return Path(f"C:/Users/{username}/AppData/Local") / APP_NAME / "config" / "config.json"
    # On Unix, per-user paths don't vary by username in the same way
    return get_config_file_path()


def _get_user_profile_path(username: str) -> Path:
    """Look up a user's profile directory via Windows registry.

    Uses win32security.LookupAccountName to get SID, then reads
    ProfileImagePath from the registry ProfileList.

    Args:
        username: OS username.

    Returns:
        Path to user's profile directory.

    Raises:
        ImportError: If pywin32 is not available.
        OSError: If the user or profile path cannot be resolved.
    """
    import win32security
    import winreg

    sid_obj, _, _ = win32security.LookupAccountName(None, username)
    sid_str = win32security.ConvertSidToStringSid(sid_obj)
    key_path = rf"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\{sid_str}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
        profile_path, _ = winreg.QueryValueEx(key, "ProfileImagePath")
    return Path(profile_path)


def _strip_comment_fields(data: dict) -> dict:
    """Recursively remove _-prefixed and $-prefixed comment fields.

    Config files support documentation comments via `_`-prefixed or
    `$`-prefixed keys (e.g., `_comment`, `$schema`). This function
    strips them before validation.

    Args:
        data: Configuration dictionary (potentially nested).

    Returns:
        Cleaned dictionary with comment fields removed.
    """
    if not isinstance(data, dict):
        return data
    return {
        k: _strip_comment_fields(v) if isinstance(v, dict) else v
        for k, v in data.items()
        if not k.startswith("_") and not k.startswith("$")
    }


def load_settings_from_file(config_path: Path | None = None) -> dict[str, Any]:
    """Load and validate settings from a config file.

    Used by the Multi-User Dispatcher to load per-user configuration
    from an explicit path instead of the default discovery location.

    Args:
        config_path: Explicit path to config file. If None, uses default.

    Returns:
        Validated configuration dictionary. Falls back to defaults if
        the file doesn't exist or contains invalid JSON.
    """
    if config_path is None:
        config_path = get_config_file_path()

    if not config_path.exists():
        return generate_default_config()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        # Strip comment fields
        stripped = _strip_comment_fields(raw)
        # Merge with defaults (ensure all required keys present)
        defaults = generate_default_config()
        if "daemon" in stripped:
            defaults["daemon"].update(stripped["daemon"])
        if "server" in stripped:
            defaults["server"].update(stripped["server"])
        return defaults
    except (json.JSONDecodeError, KeyError, TypeError):
        return generate_default_config()


def find_available_port(start: int = DEFAULT_PORT, end: int | None = None) -> int:
    """Scan for first available port in range.

    Used by the setup wizard to find an available port when the default
    port is already in use.

    Args:
        start: First port to try.
        end: Last port to try (default: start + 100).

    Returns:
        First available port number.

    Raises:
        RuntimeError: If no port is available in range.
    """
    import socket

    if end is None:
        end = start + 100
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available port in range {start}-{end}")


def generate_default_config(
    port: int | None = None,
    host: str = "127.0.0.1",
    transport: str = "sse",
    log_level: str = "DEBUG",
    config_poll_seconds: int = 3,
    wait_for_session: bool = True,
    session_poll_seconds: int = 3,
) -> dict[str, Any]:
    """Generate default configuration dictionary.

    Args:
        port: Server port (default: DEFAULT_PORT).
        host: Server host (default: 127.0.0.1).
        transport: MCP transport type (default: sse).
        log_level: Logging level (default: DEBUG).
        config_poll_seconds: Config file poll interval.
        wait_for_session: Wait for user session before starting.
        session_poll_seconds: Session poll interval.

    Returns:
        Configuration dictionary.
    """
    return {
        "daemon": {
            "enabled": True,
            "host": host,
            "port": port or DEFAULT_PORT,
            "transport": transport,
            "log_level": log_level,
            "config_poll_seconds": config_poll_seconds,
            "session_poll_seconds": session_poll_seconds,
            "wait_for_session": wait_for_session,
        },
        "server": {
            # Server-specific configuration
            # Add application-specific settings here
        },
    }


def init_config(
    force: bool = False,
    port: int | None = None,
    host: str | None = None,
    log_level: str | None = None,
    interactive: bool = True,
    username: str | None = None,
) -> Path:
    """Generate default config file with optional prompts.

    Args:
        force: Overwrite existing config file.
        port: Server port (prompts if None and interactive).
        host: Server host.
        log_level: Logging level.
        interactive: Enable interactive prompts.
        username: Optional username for multi-user scenarios.

    Returns:
        Path to created config file.

    Raises:
        FileExistsError: If config exists and force=False.
    """
    config_path = get_config_file_path(username)

    if config_path.exists() and not force:
        raise FileExistsError(f"Config already exists: {config_path}")

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Interactive prompts (if enabled and values not provided)
    if interactive:
        if port is None:
            port = _prompt_int("Port", DEFAULT_PORT)
        if log_level is None:
            log_level = _prompt_choice(
                "Log level",
                ["DEBUG", "INFO", "WARNING", "ERROR"],
                default="DEBUG",
            )

    # Generate config with provided or default values
    config = generate_default_config(
        port=port,
        host=host or "127.0.0.1",
        log_level=log_level or "DEBUG",
    )

    # Write config file
    config_path.write_text(json.dumps(config, indent=2))

    return config_path


def _prompt_int(prompt: str, default: int) -> int:
    """Prompt for integer value."""
    if HAS_TYPER:
        return typer.prompt(prompt, default=default, type=int)
    else:
        response = input(f"{prompt} [{default}]: ").strip()
        return int(response) if response else default


def _prompt_choice(prompt: str, choices: list[str], default: str) -> str:
    """Prompt for choice from list."""
    if HAS_TYPER:
        return typer.prompt(prompt, default=default)
    else:
        choices_str = "/".join(choices)
        response = input(f"{prompt} ({choices_str}) [{default}]: ").strip()
        return response if response in choices else default


# CLI integration (for direct execution)
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize config file")
    parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing")
    parser.add_argument("--port", "-p", type=int, help="Server port")
    parser.add_argument("--no-interactive", action="store_true", help="Disable prompts")
    args = parser.parse_args()

    try:
        path = init_config(
            force=args.force,
            port=args.port,
            interactive=not args.no_interactive,
        )
        print(f"Config created: {path}")
    except FileExistsError as e:
        print(f"Error: {e}")
        print("Use --force to overwrite")
        exit(1)
