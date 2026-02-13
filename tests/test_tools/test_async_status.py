"""Tests for async_status tool."""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from async_crud_mcp.config import Settings
from async_crud_mcp.core import HashRegistry, LockManager, PathValidator
from async_crud_mcp.models import AsyncStatusRequest, ErrorCode
from async_crud_mcp.tools import async_status


@pytest.fixture
def temp_base_dir():
    """Create a temporary base directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def path_validator(temp_base_dir):
    """Create PathValidator with temp base directory."""
    return PathValidator(base_directories=[str(temp_base_dir)])


@pytest.fixture
def lock_manager():
    """Create LockManager instance."""
    return LockManager()


@pytest.fixture
def hash_registry():
    """Create HashRegistry instance."""
    return HashRegistry()


@pytest.fixture
def settings(temp_base_dir):
    """Create Settings instance with test configuration."""
    settings = Settings()
    settings.crud.base_directories = [str(temp_base_dir)]
    settings.daemon.transport = "sse"
    settings.daemon.port = 8720
    settings.persistence.enabled = False
    return settings


@pytest.fixture
def server_start_time():
    """Create server start time (monotonic timestamp)."""
    return time.monotonic()


@pytest.fixture
def sample_file(temp_base_dir):
    """Create a sample file."""
    file_path = temp_base_dir / "sample.txt"
    file_path.write_text("sample content", encoding='utf-8')
    return file_path


class TestAsyncStatusGlobal:
    """Test global status (path=None)."""

    @pytest.mark.asyncio
    async def test_global_status_basic(
        self,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test basic global status response."""
        request = AsyncStatusRequest(path=None)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"

        # Verify ServerInfo
        assert response.server.version == "0.1.0"
        assert response.server.uptime_seconds >= 0
        assert response.server.transport == "sse"
        assert response.server.port == 8720
        assert response.server.persistence == "disabled"

        # Verify counts
        assert response.tracked_files == 0
        assert response.active_locks.read == 0
        assert response.active_locks.write == 0
        assert response.queue_depth == 0
        assert len(response.base_directories) > 0

    @pytest.mark.asyncio
    async def test_global_status_uptime(
        self,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test that uptime increases over time."""
        # Wait a small amount of time
        await asyncio.sleep(0.1)

        request = AsyncStatusRequest(path=None)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        # Response is GlobalStatusResponse
        assert hasattr(response, 'server')
        assert response.server.uptime_seconds >= 0.1

    @pytest.mark.asyncio
    async def test_global_status_tracked_files(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test tracked_files count with entries in HashRegistry."""
        # Add files to hash registry
        hash_registry.update(str(sample_file), "sha256:abc123")
        hash_registry.update(str(sample_file.parent / "file2.txt"), "sha256:def456")

        request = AsyncStatusRequest(path=None)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.tracked_files == 2

    @pytest.mark.asyncio
    async def test_global_status_active_locks(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test active_locks count with acquired locks."""
        # Acquire some locks
        read_id1 = await lock_manager.acquire_read(str(sample_file))
        read_id2 = await lock_manager.acquire_read(str(sample_file))

        request = AsyncStatusRequest(path=None)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.active_locks.read == 2
        assert response.active_locks.write == 0
        assert response.queue_depth == 0

        # Release locks
        await lock_manager.release_read(str(sample_file), read_id1)
        await lock_manager.release_read(str(sample_file), read_id2)

    @pytest.mark.asyncio
    async def test_global_status_persistence_enabled(
        self,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test global status with persistence enabled."""
        settings.persistence.enabled = True

        request = AsyncStatusRequest(path=None)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.server.persistence == "enabled"


class TestAsyncStatusFile:
    """Test per-file status (path provided)."""

    @pytest.mark.asyncio
    async def test_file_status_exists(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status for existing file."""
        request = AsyncStatusRequest(path=str(sample_file))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.path == str(sample_file)
        assert response.exists is True
        assert response.hash is None  # Not in registry yet
        assert response.lock_state == "unlocked"
        assert response.queue_depth == 0
        assert response.active_readers == 0
        assert isinstance(response.pending_requests, list)

    @pytest.mark.asyncio
    async def test_file_status_not_exists(
        self,
        temp_base_dir,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status for non-existent file."""
        nonexistent = temp_base_dir / "nonexistent.txt"
        request = AsyncStatusRequest(path=str(nonexistent))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.exists is False
        assert response.hash is None

    @pytest.mark.asyncio
    async def test_file_status_with_hash(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status with hash in registry."""
        # Add file to hash registry
        hash_registry.update(str(sample_file), "sha256:abc123")

        request = AsyncStatusRequest(path=str(sample_file))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.hash == "sha256:abc123"

    @pytest.mark.asyncio
    async def test_file_status_read_locked(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status with active read locks."""
        # Acquire read locks
        read_id1 = await lock_manager.acquire_read(str(sample_file))
        read_id2 = await lock_manager.acquire_read(str(sample_file))

        request = AsyncStatusRequest(path=str(sample_file))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.lock_state == "read_locked"
        assert response.active_readers == 2

        # Release locks
        await lock_manager.release_read(str(sample_file), read_id1)
        await lock_manager.release_read(str(sample_file), read_id2)

    @pytest.mark.asyncio
    async def test_file_status_write_locked(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status with active write lock."""
        # Acquire write lock
        write_id = await lock_manager.acquire_write(str(sample_file))

        request = AsyncStatusRequest(path=str(sample_file))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.lock_state == "write_locked"
        assert response.active_readers == 0

        # Release lock
        await lock_manager.release_write(str(sample_file), write_id)

    @pytest.mark.asyncio
    async def test_file_status_unlocked(
        self,
        sample_file,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status with no locks."""
        request = AsyncStatusRequest(path=str(sample_file))
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "ok"
        assert response.lock_state == "unlocked"
        assert response.active_readers == 0


class TestAsyncStatusErrors:
    """Test error conditions."""

    @pytest.mark.asyncio
    async def test_file_status_path_outside_base(
        self,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time
    ):
        """Test file status for path outside base directory."""
        outside_path = "/tmp/outside.txt"
        request = AsyncStatusRequest(path=outside_path)
        response = await async_status(
            request,
            path_validator,
            lock_manager,
            hash_registry,
            settings,
            server_start_time
        )

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE
