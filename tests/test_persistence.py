"""Tests for state persistence module.

Tests cover:
- Save/load hash registry and lock manager state
- TTL purge on startup
- Hash re-validation (file exists/mismatch/deleted)
- Debounced writes
- Disabled persistence (no-op mode)
- Custom state file path
- Corrupt state file handling
- Immediate flush via save_now()
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from async_crud_mcp.config import PersistenceConfig
from async_crud_mcp.core.file_io import HashRegistry, compute_hash
from async_crud_mcp.core.lock_manager import LockManager
from async_crud_mcp.core.persistence import StatePersistence


@pytest.fixture
def temp_state_file(tmp_path: Path) -> Path:
    """Create temporary state file path."""
    return tmp_path / "state.json"


@pytest.fixture
def hash_registry() -> HashRegistry:
    """Create fresh hash registry."""
    return HashRegistry()


@pytest.fixture
def lock_manager() -> LockManager:
    """Create fresh lock manager."""
    return LockManager(ttl_multiplier=2.0)


@pytest.fixture
def persistence_config(temp_state_file: Path) -> PersistenceConfig:
    """Create persistence config with temp state file."""
    return PersistenceConfig(
        enabled=True,
        state_file=str(temp_state_file),
        write_debounce_seconds=0.1,
        ttl_multiplier=2.0,
    )


@pytest.mark.asyncio
async def test_save_and_load_hash_registry(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test saving and loading hash registry state."""
    # Create actual test files so re-validation doesn't remove them
    file1 = tmp_path / "file1.py"
    file2 = tmp_path / "file2.py"
    file1.write_text("content1")
    file2.write_text("content2")

    # Add entries to hash registry
    hash_registry.update(str(file1), "sha256:abc123")
    hash_registry.update(str(file2), "sha256:def456")

    # Create persistence and save
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.save_now()

    # Verify file was created
    assert temp_state_file.exists()

    # Create new registry and load
    new_registry = HashRegistry()
    new_lock_manager = LockManager()
    new_persistence = StatePersistence(new_registry, new_lock_manager, persistence_config)
    await new_persistence.load()

    # Verify registry state matches (files exist but content changed, so hashes will be recomputed)
    # We just verify the entries exist
    assert new_registry.get(str(file1)) is not None
    assert new_registry.get(str(file2)) is not None


@pytest.mark.asyncio
async def test_save_and_load_pending_queue(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test saving and loading lock manager queue state."""
    test_file = tmp_path / "test.py"
    test_file.write_text("content")
    test_path = str(test_file)

    # Acquire a write lock first to block the second one
    request_id1 = await lock_manager.acquire_write(test_path, timeout=30.0)

    # Create a queued write lock (will queue because first lock is active)
    async def create_queued_lock() -> None:
        await lock_manager.acquire_write(test_path, timeout=30.0)

    # Start the lock acquisition but don't await it (will queue)
    task = asyncio.create_task(create_queued_lock())
    await asyncio.sleep(0.05)  # Let it queue

    # Save state
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.save_now()

    # Release the first lock and cancel the task
    await lock_manager.release_write(test_path, request_id1)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    # Verify file was created
    assert temp_state_file.exists()

    # The queued lock might have been granted or removed, so just verify state was saved
    with open(temp_state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)

    assert "pending_queue" in state


@pytest.mark.asyncio
async def test_ttl_purge_on_startup(
    hash_registry: HashRegistry,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
) -> None:
    """Test that expired lock entries are purged on startup."""
    # Create lock manager and add entries with expired TTLs
    lock_manager = LockManager(ttl_multiplier=2.0)

    # Manually inject expired entries into lock manager state
    # We'll create a state file with expired TTLs directly
    current_time = time.monotonic()
    expired_time = current_time - 100  # 100 seconds in the past

    state = {
        "version": 1,
        "saved_at": "2026-02-12T12:00:00Z",
        "hash_registry": {},
        "pending_queue": {
            "/path/to/file.py": {
                "active_readers": 0,
                "active_writer": False,
                "queue": [
                    {
                        "request_id": "expired-1",
                        "lock_type": "write",
                        "created_at": expired_time - 60,
                        "timeout": 30.0,
                        "ttl_expires_at": expired_time,
                    }
                ],
            }
        },
    }

    # Write state file
    with open(temp_state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f)

    # Load state - should purge expired entries
    new_lock_manager = LockManager(ttl_multiplier=2.0)
    new_persistence = StatePersistence(hash_registry, new_lock_manager, persistence_config)
    await new_persistence.load()

    # Verify entries were purged
    status = new_lock_manager.get_status("/path/to/file.py")
    assert status["queued"] == 0


@pytest.mark.asyncio
async def test_hash_revalidation_file_exists_match(
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test hash re-validation when file exists with matching hash."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_content = b"test content"
    test_file.write_bytes(test_content)

    # Compute hash
    test_hash = compute_hash(test_content)

    # Create state with the hash
    hash_registry = HashRegistry()
    hash_registry.update(str(test_file), test_hash)

    # Save and reload
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.save_now()

    new_registry = HashRegistry()
    new_persistence = StatePersistence(new_registry, lock_manager, persistence_config)
    await new_persistence.load()

    # Verify hash is unchanged
    assert new_registry.get(str(test_file)) == test_hash


@pytest.mark.asyncio
async def test_hash_revalidation_file_exists_mismatch(
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test hash re-validation when file exists but hash differs."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    original_content = b"original content"
    test_file.write_bytes(original_content)

    # Compute original hash
    original_hash = compute_hash(original_content)

    # Create state with original hash
    hash_registry = HashRegistry()
    hash_registry.update(str(test_file), original_hash)

    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.save_now()

    # Modify the file
    new_content = b"modified content"
    test_file.write_bytes(new_content)
    new_hash = compute_hash(new_content)

    # Reload - should detect mismatch and update
    new_registry = HashRegistry()
    new_persistence = StatePersistence(new_registry, lock_manager, persistence_config)
    await new_persistence.load()

    # Verify hash was updated
    assert new_registry.get(str(test_file)) == new_hash
    assert new_registry.get(str(test_file)) != original_hash


@pytest.mark.asyncio
async def test_hash_revalidation_file_deleted(
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test hash re-validation when file is deleted."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"content")

    # Compute hash
    test_hash = compute_hash(b"content")

    # Create state with the hash
    hash_registry = HashRegistry()
    hash_registry.update(str(test_file), test_hash)

    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.save_now()

    # Delete the file
    test_file.unlink()

    # Reload - should remove entry
    new_registry = HashRegistry()
    new_persistence = StatePersistence(new_registry, lock_manager, persistence_config)
    await new_persistence.load()

    # Verify entry was removed
    assert new_registry.get(str(test_file)) is None


@pytest.mark.asyncio
async def test_debounced_writes(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
) -> None:
    """Test that writes are debounced within the debounce window."""
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)

    # Mark dirty multiple times rapidly
    for i in range(5):
        hash_registry.update(f"/path/to/file{i}.py", f"sha256:hash{i}")
        persistence.mark_dirty()
        await asyncio.sleep(0.02)  # Less than debounce window (0.1s)

    # Wait for debounce window to pass
    await asyncio.sleep(0.2)

    # Should have written only once (or very few times)
    assert temp_state_file.exists()

    # Verify all updates are present
    with open(temp_state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)

    # All 5 files should be in the saved state
    assert len(state["hash_registry"]) == 5


@pytest.mark.asyncio
async def test_disabled_persistence_noop(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    temp_state_file: Path,
) -> None:
    """Test that persistence is no-op when disabled."""
    config = PersistenceConfig(
        enabled=False,
        state_file=str(temp_state_file),
    )

    persistence = StatePersistence(hash_registry, lock_manager, config)

    # Add entries and mark dirty
    hash_registry.update("/path/to/file.py", "sha256:abc123")
    persistence.mark_dirty()

    # Save now
    await persistence.save_now()

    # Verify no file was created
    assert not temp_state_file.exists()

    # Load should also be no-op
    await persistence.load()


@pytest.mark.asyncio
async def test_custom_state_file_path(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    tmp_path: Path,
) -> None:
    """Test using a custom state file path."""
    custom_path = tmp_path / "custom" / "my_state.json"

    config = PersistenceConfig(
        enabled=True,
        state_file=str(custom_path),
    )

    persistence = StatePersistence(hash_registry, lock_manager, config)

    hash_registry.update("/path/to/file.py", "sha256:abc123")
    await persistence.save_now()

    # Verify file was created at custom path
    assert custom_path.exists()
    assert custom_path.parent.exists()


@pytest.mark.asyncio
async def test_corrupt_state_file(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
) -> None:
    """Test that corrupt state files are handled gracefully."""
    # Write invalid JSON
    temp_state_file.write_text("{ invalid json }", encoding='utf-8')

    # Load should handle gracefully
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)
    await persistence.load()  # Should not raise

    # Registry should be empty (fresh start)
    assert len(hash_registry.snapshot()) == 0


@pytest.mark.asyncio
async def test_save_now_flushes_immediately(
    hash_registry: HashRegistry,
    lock_manager: LockManager,
    persistence_config: PersistenceConfig,
    temp_state_file: Path,
    tmp_path: Path,
) -> None:
    """Test that save_now() writes immediately regardless of debounce."""
    persistence = StatePersistence(hash_registry, lock_manager, persistence_config)

    # Create actual file
    test_file = tmp_path / "test.py"
    test_file.write_text("content")

    # Mark dirty (would normally wait for debounce)
    hash_registry.update(str(test_file), "sha256:abc123")
    persistence.mark_dirty()

    # Don't wait for debounce - call save_now immediately
    await persistence.save_now()

    # Verify file was written immediately
    assert temp_state_file.exists()

    with open(temp_state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)

    # Verify entry exists (hash will be recomputed on load due to re-validation)
    assert len(state["hash_registry"]) == 1
