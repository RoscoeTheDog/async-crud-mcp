"""Tests for async_write tool."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncWriteRequest, ErrorCode
from async_crud_mcp.tools import async_write


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


class TestAsyncWriteSuccess:
    """Test successful write operations."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test successful write creates new file with correct content and hash."""
        file_path = temp_base_dir / "new_file.txt"
        content = "Hello, World!"
        request = AsyncWriteRequest(path=str(file_path), content=content)

        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.path == str(file_path)
        assert response.bytes_written == len(content.encode('utf-8'))
        assert response.hash.startswith("sha256:")

        # Verify file was actually written
        assert file_path.exists()
        assert file_path.read_text(encoding='utf-8') == content

        # Verify hash matches
        expected_hash = compute_hash(content.encode('utf-8'))
        assert response.hash == expected_hash

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_dirs=True creates parent directories."""
        file_path = temp_base_dir / "subdir1" / "subdir2" / "file.txt"
        content = "test content"
        request = AsyncWriteRequest(path=str(file_path), content=content, create_dirs=True)

        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.exists()
        assert file_path.parent.exists()
        assert file_path.read_text(encoding='utf-8') == content

    @pytest.mark.asyncio
    async def test_write_updates_hash_registry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry is updated after successful write."""
        file_path = temp_base_dir / "registry_test.txt"
        content = "registry test"
        request = AsyncWriteRequest(path=str(file_path), content=content)

        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify hash registry was updated
        registered_hash = hash_registry.get(str(file_path))
        assert registered_hash == response.hash

    @pytest.mark.asyncio
    async def test_hash_matches_file_on_disk(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test hash in response matches recomputed hash of file on disk."""
        file_path = temp_base_dir / "hash_verify.txt"
        content = "verify hash content"
        request = AsyncWriteRequest(path=str(file_path), content=content)

        response = await async_write(request, path_validator, lock_manager, hash_registry)

        # Recompute hash from disk
        disk_content = file_path.read_bytes()
        disk_hash = compute_hash(disk_content)

        assert response.hash == disk_hash

    @pytest.mark.asyncio
    async def test_bytes_written_correct(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test atomic write produces correct bytes_written count."""
        file_path = temp_base_dir / "bytes_test.txt"
        content = "test with special chars: é ñ"
        request = AsyncWriteRequest(path=str(file_path), content=content, encoding='utf-8')

        response = await async_write(request, path_validator, lock_manager, hash_registry)

        expected_bytes = len(content.encode('utf-8'))
        assert response.bytes_written == expected_bytes


class TestAsyncWriteErrors:
    """Test error handling in write operations."""

    @pytest.mark.asyncio
    async def test_file_exists_error(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test FILE_EXISTS error when file already exists."""
        file_path = temp_base_dir / "existing.txt"
        file_path.write_text("already exists", encoding='utf-8')

        request = AsyncWriteRequest(path=str(file_path), content="new content")
        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_EXISTS
        assert "already exists" in response.message.lower()

    @pytest.mark.asyncio
    async def test_path_outside_base(self, path_validator, lock_manager, hash_registry):
        """Test PATH_OUTSIDE_BASE error for invalid path."""
        outside_path = "/tmp/outside_base.txt"
        request = AsyncWriteRequest(path=outside_path, content="test")
        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_create_dirs_false_parent_missing(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_dirs=False fails when parent directory missing."""
        file_path = temp_base_dir / "missing_parent" / "file.txt"
        request = AsyncWriteRequest(path=str(file_path), content="test", create_dirs=False)
        response = await async_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.WRITE_ERROR

    @pytest.mark.asyncio
    async def test_lock_timeout(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test LOCK_TIMEOUT when write lock cannot be acquired."""
        file_path = temp_base_dir / "locked_file.txt"

        # Acquire write lock manually with long timeout
        write_request_id = await lock_manager.acquire_write(str(file_path), timeout=10.0)

        try:
            # Try to write with short timeout (should timeout)
            request = AsyncWriteRequest(path=str(file_path), content="test", timeout=0.1)
            response = await async_write(request, path_validator, lock_manager, hash_registry)

            assert response.status == "error"
            assert response.error_code == ErrorCode.LOCK_TIMEOUT
            assert "0.1" in response.message

        finally:
            await lock_manager.release_write(str(file_path), write_request_id)


class TestAsyncWriteConcurrency:
    """Test concurrent write operations."""

    @pytest.mark.asyncio
    async def test_exclusive_lock_prevents_concurrent_writes(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test exclusive lock prevents concurrent writes."""
        file_path = temp_base_dir / "concurrent_write.txt"

        # Acquire write lock
        write_request_id = await lock_manager.acquire_write(str(file_path), timeout=5.0)

        try:
            # Try to write while lock is held
            request = AsyncWriteRequest(path=str(file_path), content="test", timeout=0.1)
            write_task = asyncio.create_task(
                async_write(request, path_validator, lock_manager, hash_registry)
            )

            # Wait a bit to ensure write is blocked
            await asyncio.sleep(0.1)

            # Write should still be pending or should have timed out
            if write_task.done():
                response = write_task.result()
                assert response.status == "error"
                assert response.error_code == ErrorCode.LOCK_TIMEOUT
            else:
                # Still blocked - cancel it
                write_task.cancel()
                try:
                    await write_task
                except asyncio.CancelledError:
                    pass

        finally:
            await lock_manager.release_write(str(file_path), write_request_id)
