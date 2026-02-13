"""Tests for async_rename tool."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncRenameRequest, ErrorCode
from async_crud_mcp.tools import async_rename


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


class TestAsyncRenameSuccess:
    """Test successful rename operations."""

    @pytest.mark.asyncio
    async def test_rename_basic(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test basic rename changes file path."""
        old_path = temp_base_dir / "old_name.txt"
        new_path = temp_base_dir / "new_name.txt"
        content = "File to be renamed"
        old_path.write_text(content, encoding='utf-8')

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path))
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.old_path == str(old_path)
        assert response.new_path == str(new_path)
        assert response.hash.startswith("sha256:")
        assert not old_path.exists()
        assert new_path.exists()
        assert new_path.read_text(encoding='utf-8') == content

    @pytest.mark.asyncio
    async def test_rename_with_create_dirs(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_dirs=True creates parent directories for destination."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "subdir1" / "subdir2" / "destination.txt"
        content = "Test content"
        old_path.write_text(content, encoding='utf-8')

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), create_dirs=True)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert new_path.exists()
        assert new_path.parent.exists()
        assert new_path.read_text(encoding='utf-8') == content

    @pytest.mark.asyncio
    async def test_rename_with_overwrite(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test overwrite=True allows replacing existing destination file."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "destination.txt"
        old_content = "Source content"
        new_content = "Destination content (will be overwritten)"

        old_path.write_text(old_content, encoding='utf-8')
        new_path.write_text(new_content, encoding='utf-8')

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), overwrite=True)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert new_path.read_text(encoding='utf-8') == old_content

    @pytest.mark.asyncio
    async def test_rename_with_matching_expected_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename succeeds when expected_hash matches source file hash."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "dest.txt"
        content = "Hash should match"
        old_path.write_text(content, encoding='utf-8')

        expected_hash = compute_hash(content.encode('utf-8'))
        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), expected_hash=expected_hash)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.hash == expected_hash

    @pytest.mark.asyncio
    async def test_rename_updates_hash_registry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry is updated with new path after rename."""
        old_path = temp_base_dir / "old.txt"
        new_path = temp_base_dir / "new.txt"
        content = "Registry test"
        old_path.write_text(content, encoding='utf-8')

        # Pre-populate old path in registry
        old_hash = compute_hash(content.encode('utf-8'))
        hash_registry.update(str(old_path), old_hash)

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path))
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify old path removed and new path added
        assert hash_registry.get(str(old_path)) is None
        assert hash_registry.get(str(new_path)) == response.hash


class TestAsyncRenameContention:
    """Test contention detection with expected_hash."""

    @pytest.mark.asyncio
    async def test_rename_with_mismatching_expected_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename returns ContentionResponse when expected_hash doesn't match."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "dest.txt"
        content = "Original content"
        old_path.write_text(content, encoding='utf-8')

        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), expected_hash=wrong_hash)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.expected_hash == wrong_hash
        assert response.current_hash.startswith("sha256:")
        assert response.current_hash != wrong_hash

        # Verify file not renamed
        assert old_path.exists()
        assert not new_path.exists()


class TestAsyncRenameDualLock:
    """Test dual-lock behavior for deadlock prevention."""

    @pytest.mark.asyncio
    async def test_rename_alphabetical_lock_ordering(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename acquires locks in alphabetical order."""
        # Create two files with names that will test alphabetical ordering
        file_a = temp_base_dir / "aaa.txt"
        file_z = temp_base_dir / "zzz.txt"
        file_a.write_text("Content A", encoding='utf-8')

        request = AsyncRenameRequest(old_path=str(file_a), new_path=str(file_z))
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Test reverse order (z -> a)
        file_z2 = temp_base_dir / "zzz2.txt"
        file_a2 = temp_base_dir / "aaa2.txt"
        file_z2.write_text("Content Z", encoding='utf-8')

        request2 = AsyncRenameRequest(old_path=str(file_z2), new_path=str(file_a2))
        response2 = await async_rename(request2, path_validator, lock_manager, hash_registry)

        assert response2.status == "ok"


class TestAsyncRenameErrors:
    """Test error handling in rename operations."""

    @pytest.mark.asyncio
    async def test_rename_source_not_found(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename returns FILE_NOT_FOUND when source doesn't exist."""
        old_path = temp_base_dir / "nonexistent.txt"
        new_path = temp_base_dir / "destination.txt"

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path))
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_rename_dest_exists_without_overwrite(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename returns FILE_EXISTS when destination exists and overwrite=False."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "existing.txt"
        old_path.write_text("Source", encoding='utf-8')
        new_path.write_text("Existing", encoding='utf-8')

        request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), overwrite=False)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_EXISTS

    @pytest.mark.asyncio
    async def test_rename_path_outside_base(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename returns PATH_OUTSIDE_BASE when path is outside allowed directories."""
        old_path = temp_base_dir / "file.txt"
        old_path.write_text("content", encoding='utf-8')
        outside_path = "/etc/passwd"

        request = AsyncRenameRequest(old_path=str(old_path), new_path=outside_path)
        response = await async_rename(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_rename_lock_timeout(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test rename returns LOCK_TIMEOUT when lock cannot be acquired."""
        old_path = temp_base_dir / "locked.txt"
        new_path = temp_base_dir / "dest.txt"
        old_path.write_text("content", encoding='utf-8')

        # Pre-acquire write lock on source
        lock_id = await lock_manager.acquire_write(str(old_path))

        try:
            request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path), timeout=0.1)
            response = await async_rename(request, path_validator, lock_manager, hash_registry)

            assert response.status == "error"
            assert response.error_code == ErrorCode.LOCK_TIMEOUT
        finally:
            await lock_manager.release_write(str(old_path), lock_id)


class TestAsyncRenameCrossFilesystem:
    """Test cross-filesystem rename fallback."""

    @pytest.mark.asyncio
    async def test_rename_cross_filesystem_flag(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test cross_filesystem flag is set correctly when filesystems differ."""
        old_path = temp_base_dir / "source.txt"
        new_path = temp_base_dir / "dest.txt"
        content = "Test content"
        old_path.write_text(content, encoding='utf-8')

        # Mock safe_rename to simulate cross-filesystem rename.
        # Directly patching os.stat is unreliable because both source file and
        # destination directory share the same temp dir prefix, so both stat
        # calls return the mocked st_dev, making them appear on the same FS.
        def fake_cross_fs_rename(src, dst):
            """Perform the actual rename but report it as cross-filesystem."""
            shutil.copy2(src, dst)
            os.unlink(src)
            return True  # Indicate cross-filesystem

        with patch('async_crud_mcp.tools.async_rename.safe_rename', side_effect=fake_cross_fs_rename):
            request = AsyncRenameRequest(old_path=str(old_path), new_path=str(new_path))
            response = await async_rename(request, path_validator, lock_manager, hash_registry)

            assert response.status == "ok"
            assert response.cross_filesystem is True
