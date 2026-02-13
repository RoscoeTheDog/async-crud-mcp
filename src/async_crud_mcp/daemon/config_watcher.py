"""Config file watcher with debounce protection.

This module provides a config file watcher that handles common issues:
- Mid-write reads (editor saves in multiple operations)
- Validation failures (bad config doesn't crash daemon)
- Last-known-good caching

Usage:
    from config_watcher import ConfigWatcher, ResilientConfigLoader

    watcher = ConfigWatcher(config_path, debounce_seconds=1.0)

    while True:
        if watcher.check_for_changes():
            config = loader.load()
            apply_config(config)
        time.sleep(3)
"""

import time
import json
from pathlib import Path
from typing import Optional, TypeVar, Generic
from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)


class ConfigWatcher:
    """Watch a config file for changes with debounce protection.

    The debounce prevents reading the file while an editor is still
    writing (many editors save in multiple write operations).
    """

    def __init__(
        self,
        config_path: Path,
        poll_seconds: float = 5.0,
        debounce_seconds: float = 1.0
    ):
        """Initialize the config watcher.

        Args:
            config_path: Path to the config file
            poll_seconds: How often to check (informational, caller controls)
            debounce_seconds: Minimum time after last change before reading
        """
        self.config_path = Path(config_path)
        self.poll_seconds = poll_seconds
        self.debounce_seconds = debounce_seconds
        self._last_mtime: float = 0
        self._last_change_detected: float = 0

    def check_for_changes(self) -> bool:
        """Check if config changed, with debounce protection.

        Returns:
            True if config changed and debounce window passed (safe to read)
            False if no change or within debounce window

        Example:
            >>> watcher = ConfigWatcher(Path("config.json"))
            >>> if watcher.check_for_changes():
            ...     config = load_config()
        """
        try:
            current_mtime = self.config_path.stat().st_mtime
        except FileNotFoundError:
            return False

        if current_mtime != self._last_mtime:
            now = time.time()
            if self._last_change_detected == 0:
                # First change detection - start debounce window
                self._last_change_detected = now
                return False
            elif now - self._last_change_detected < self.debounce_seconds:
                # Within debounce window - wait for writes to settle
                return False
            else:
                # Debounce window passed - safe to read
                self._last_mtime = current_mtime
                self._last_change_detected = 0
                return True
        return False

    def reset(self) -> None:
        """Reset the watcher state.

        Call this after a successful config load to prevent
        immediate re-triggering.
        """
        try:
            self._last_mtime = self.config_path.stat().st_mtime
        except FileNotFoundError:
            self._last_mtime = 0
        self._last_change_detected = 0


class ResilientConfigLoader(Generic[T]):
    """Load config with fallback to last-known-good on validation failure.

    This prevents the daemon from crashing when a user makes a typo
    in the config file.
    """

    def __init__(
        self,
        config_path: Path,
        config_class: type[T],
        strip_comments: bool = True
    ):
        """Initialize the config loader.

        Args:
            config_path: Path to the config file
            config_class: Pydantic model class for validation
            strip_comments: Remove _-prefixed and $-prefixed keys
        """
        self.config_path = Path(config_path)
        self.config_class = config_class
        self.strip_comments = strip_comments
        self._last_valid_config: Optional[T] = None

    def load(self) -> T:
        """Load config with fallback to last-known-good on validation failure.

        Returns:
            Validated config object

        Raises:
            ValidationError: If validation fails and no last-known-good exists
            json.JSONDecodeError: If JSON is invalid and no fallback exists

        Example:
            >>> loader = ResilientConfigLoader(path, MyConfig)
            >>> config = loader.load()
        """
        try:
            raw_text = self.config_path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)

            if self.strip_comments:
                raw_data = self._strip_comment_fields(raw_data)

            config = self.config_class.model_validate(raw_data)
            self._last_valid_config = config
            return config

        except ValidationError as e:
            if self._last_valid_config:
                # Log would go here in real implementation
                print(f"Config validation failed, using last-known-good: {e}")
                return self._last_valid_config
            else:
                print(f"Config validation failed, no fallback available: {e}")
                raise

        except json.JSONDecodeError as e:
            if self._last_valid_config:
                print(f"Config JSON invalid, using last-known-good: {e}")
                return self._last_valid_config
            else:
                raise

    def _strip_comment_fields(self, data: dict) -> dict:
        """Recursively remove comment fields from config data.

        Comment fields are those prefixed with _ or $ (e.g., _comment, $schema).
        """
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            # Skip comment fields
            if key.startswith("_") or key.startswith("$"):
                continue
            # Recurse into nested dicts
            if isinstance(value, dict):
                result[key] = self._strip_comment_fields(value)
            elif isinstance(value, list):
                result[key] = [
                    self._strip_comment_fields(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    @property
    def has_fallback(self) -> bool:
        """Check if a last-known-good config is available."""
        return self._last_valid_config is not None


def atomic_write_config(config_path: Path, data: dict) -> None:
    """Atomically write config to prevent mid-write reads.

    Writes to a temp file then renames, which is atomic on most filesystems.

    Args:
        config_path: Target config file path
        data: Config data to write
    """
    config_path = Path(config_path)
    temp_path = config_path.with_suffix(".tmp")

    # Write to temp file
    temp_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

    # Atomic rename
    temp_path.replace(config_path)


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Config Watcher Test")
    parser.add_argument("config_path", help="Path to config file")
    parser.add_argument("--watch", action="store_true", help="Watch for changes")
    args = parser.parse_args()

    path = Path(args.config_path)
    watcher = ConfigWatcher(path)

    if args.watch:
        print(f"Watching {path} for changes...")
        while True:
            if watcher.check_for_changes():
                print(f"Config changed at {time.strftime('%H:%M:%S')}")
            time.sleep(1)
    else:
        print(f"Config path: {path}")
        print(f"Exists: {path.exists()}")
        if path.exists():
            print(f"Size: {path.stat().st_size} bytes")
            print(f"Modified: {time.ctime(path.stat().st_mtime)}")
