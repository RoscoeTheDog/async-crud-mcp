"""Optional state persistence for hash registry and lock manager.

This module provides debounced state persistence to disk, enabling the server
to recover from restarts without losing hash registry and lock queue state.

Architecture:
- StatePersistence orchestrates loading/saving state.json
- Debounced writes (default 1.0s) minimize disk I/O
- Startup recovery includes TTL purge and hash re-validation
- Enable/disable toggle via PersistenceConfig.enabled (default: False)
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from ..config import PersistenceConfig
from ..daemon.paths import get_data_dir
from .file_io import HashRegistry, atomic_write, compute_file_hash
from .lock_manager import LockManager


class StatePersistence:
    """Manages persistence of hash registry and lock manager state.

    When enabled, coordinates debounced writes to state.json and performs
    startup recovery (TTL purge + hash re-validation).

    When disabled, all methods are no-ops for zero overhead.
    """

    def __init__(
        self,
        hash_registry: HashRegistry,
        lock_manager: LockManager,
        config: PersistenceConfig,
    ) -> None:
        """Initialize state persistence.

        Args:
            hash_registry: Hash registry instance to persist
            lock_manager: Lock manager instance to persist
            config: Persistence configuration
        """
        self._hash_registry = hash_registry
        self._lock_manager = lock_manager
        self._config = config
        self._enabled = config.enabled

        # Resolve state file path
        if config.state_file is not None:
            self._state_file = Path(config.state_file)
        else:
            self._state_file = get_data_dir() / 'state.json'

        # Debounce mechanism
        self._dirty = False
        self._save_handle: Optional[asyncio.TimerHandle] = None
        self._save_lock = asyncio.Lock()

    async def load(self) -> None:
        """Load state from disk and perform startup recovery.

        Steps:
        1. Read state.json (if exists)
        2. Restore hash registry
        3. Restore lock manager state
        4. Purge expired lock entries (TTL-based)
        5. Re-validate hash registry entries
        6. Save cleaned state back to disk

        This is a no-op if persistence is disabled.
        """
        if not self._enabled:
            return

        if not self._state_file.exists():
            logger.info(f"No state file found at {self._state_file}, starting fresh")
            return

        try:
            with open(self._state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            logger.info(f"Loading state from {self._state_file}")

            # Restore hash registry
            if 'hash_registry' in state:
                self._hash_registry.restore(state['hash_registry'])
                logger.debug(f"Restored {len(state['hash_registry'])} hash registry entries")

            # Restore lock manager
            if 'pending_queue' in state:
                await self._lock_manager.restore(state['pending_queue'])
                logger.debug(f"Restored lock manager state with {len(state['pending_queue'])} file locks")

            # Purge expired lock entries
            purged = await self._lock_manager.purge_expired()
            if purged > 0:
                logger.info(f"Purged {purged} expired lock entries on startup")

            # Re-validate hash registry
            await self._revalidate_hashes()

            # Save cleaned state
            await self.save_now()

        except json.JSONDecodeError as e:
            logger.error(f"Corrupt state file at {self._state_file}: {e}")
            logger.info("Starting with fresh state")
        except Exception as e:
            logger.error(f"Error loading state from {self._state_file}: {e}")
            logger.info("Starting with fresh state")

    async def _revalidate_hashes(self) -> None:
        """Re-validate all hash registry entries against actual files.

        For each (path, hash) pair in the registry:
        - If file doesn't exist: remove from registry
        - If file exists but hash differs: update registry with new hash
        - If file exists and hash matches: keep as-is

        Logs warnings for mismatches and info for deletions.
        """
        snapshot = self._hash_registry.snapshot()
        removed = 0
        updated = 0

        for path, stored_hash in snapshot.items():
            try:
                # Check if file exists
                if not Path(path).exists():
                    self._hash_registry.remove(path)
                    removed += 1
                    logger.info(f"Removed deleted file from registry: {path}")
                    continue

                # Compute current hash
                current_hash = compute_file_hash(path)

                # Check if hash matches
                if current_hash != stored_hash:
                    self._hash_registry.update(path, current_hash)
                    updated += 1
                    logger.warning(
                        f"Hash mismatch for {path}: stored={stored_hash[:16]}..., "
                        f"current={current_hash[:16]}... (external modification detected)"
                    )

            except (OSError, PermissionError) as e:
                # Log and skip files that can't be accessed
                logger.warning(f"Error re-validating {path}: {e}")
                continue

        if removed > 0 or updated > 0:
            logger.info(f"Hash registry re-validation: {removed} removed, {updated} updated")

    def mark_dirty(self) -> None:
        """Mark state as dirty and schedule debounced write.

        Schedules a write to occur after write_debounce_seconds. If called
        again before the timer fires, the timer is reset (debouncing).

        This is a no-op if persistence is disabled.
        """
        if not self._enabled:
            return

        self._dirty = True

        # Cancel existing timer if any
        if self._save_handle is not None:
            self._save_handle.cancel()

        # Schedule new timer
        loop = asyncio.get_event_loop()
        self._save_handle = loop.call_later(
            self._config.write_debounce_seconds,
            lambda: asyncio.create_task(self._do_save())
        )

    async def _do_save(self) -> None:
        """Internal method for debounced save operation."""
        async with self._save_lock:
            if not self._dirty:
                return

            await self._save()
            self._dirty = False
            self._save_handle = None

    async def save_now(self) -> None:
        """Force immediate save, bypassing debounce timer.

        Used during graceful shutdown to ensure all state is persisted.

        This is a no-op if persistence is disabled.
        """
        if not self._enabled:
            return

        async with self._save_lock:
            # Cancel pending timer if any
            if self._save_handle is not None:
                self._save_handle.cancel()
                self._save_handle = None

            await self._save()
            self._dirty = False

    async def _save(self) -> None:
        """Internal method to serialize and write state to disk.

        Creates state.json with:
        - version: Schema version (currently 1)
        - saved_at: ISO8601 timestamp
        - hash_registry: Hash registry snapshot
        - pending_queue: Lock manager snapshot
        """
        try:
            # Ensure parent directory exists
            self._state_file.parent.mkdir(parents=True, exist_ok=True)

            # Build state structure
            state: dict[str, Any] = {
                "version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "hash_registry": self._hash_registry.snapshot(),
                "pending_queue": self._lock_manager.snapshot(),
            }

            # Serialize to JSON bytes
            content = json.dumps(state, indent=2).encode('utf-8')

            # Write atomically
            atomic_write(str(self._state_file), content)

            logger.debug(f"Saved state to {self._state_file}")

        except Exception as e:
            logger.error(f"Error saving state to {self._state_file}: {e}")
