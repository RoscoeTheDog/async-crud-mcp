"""Tests for async_delete tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncDeleteRequest, ErrorCode
from async_crud_mcp.tools import async_delete


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


class TestAsyncDeleteSuccess:
    """Test successful delete operations."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test successful delete removes file and returns deleted hash."""
        file_path = temp_base_dir / "delete_me.txt"
        content = "This file will be deleted"
        file_path.write_text(content, encoding='utf-8')

        request = AsyncDeleteRequest(path=str(file_path))
        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.path == str(file_path)
        assert response.deleted_hash.startswith("sha256:")
        assert not file_path.exists()

        # Verify hash matches original file
        expected_hash = compute_hash(content.encode('utf-8'))
        assert response.deleted_hash == expected_hash

    @pytest.mark.asyncio
    async def test_delete_with_matching_expected_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test delete succeeds when expected_hash matches file hash."""
        file_path = temp_base_dir / "hash_match.txt"
        content = "Hash should match"
        file_path.write_text(content, encoding='utf-8')

        expected_hash = compute_hash(content.encode('utf-8'))
        request = AsyncDeleteRequest(path=str(file_path), expected_hash=expected_hash)
        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.deleted_hash == expected_hash
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_removes_from_hash_registry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry entry is removed after successful delete."""
        file_path = temp_base_dir / "registry_delete.txt"
        content = "Registry entry should be removed"
        file_path.write_text(content, encoding='utf-8')

        # Pre-populate registry
        file_hash = compute_hash(content.encode('utf-8'))
        hash_registry.update(str(file_path), file_hash)

        request = AsyncDeleteRequest(path=str(file_path))
        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify hash registry entry was removed
        registered_hash = hash_registry.get(str(file_path))
        assert registered_hash is None


class TestAsyncDeleteContention:
    """Test contention detection with expected_hash."""

    @pytest.mark.asyncio
    async def test_delete_with_mismatching_expected_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test delete returns ContentionResponse when expected_hash doesn't match."""
        file_path = temp_base_dir / "hash_mismatch.txt"
        original_content = "Original content"
        file_path.write_text(original_content, encoding='utf-8')

        # Use wrong hash
        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        request = AsyncDeleteRequest(path=str(file_path), expected_hash=wrong_hash)
        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.expected_hash == wrong_hash
        assert response.current_hash.startswith("sha256:")
        assert response.current_hash != wrong_hash
        assert "modified" in response.message.lower()

        # Verify file still exists
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_contention_includes_diff(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test contention response includes diff between expected and current."""
        file_path = temp_base_dir / "diff_test.txt"
        content = "Current file content\nLine 2\nLine 3"
        file_path.write_text(content, encoding='utf-8')

        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        request = AsyncDeleteRequest(path=str(file_path), expected_hash=wrong_hash, diff_format="json")
        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.diff is not None
        assert response.diff.format == "json"


class TestAsyncDeleteErrors:
    """Test error handling in delete operations."""

    @pytest.mark.asyncio
    async def test_delete_file_not_found(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test delete returns FILE_NOT_FOUND when file doesn't exist."""
        file_path = temp_base_dir / "nonexistent.txt"
        request = AsyncDeleteRequest(path=str(file_path))

        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND
        assert "not found" in response.message.lower()

    @pytest.mark.asyncio
    async def test_delete_path_outside_base(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test delete returns PATH_OUTSIDE_BASE when path is outside allowed directories."""
        outside_path = "/etc/passwd"
        request = AsyncDeleteRequest(path=outside_path)

        response = await async_delete(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_delete_lock_timeout(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test delete returns LOCK_TIMEOUT when lock cannot be acquired."""
        file_path = temp_base_dir / "locked_file.txt"
        file_path.write_text("content", encoding='utf-8')

        # Pre-acquire write lock
        lock_id = await lock_manager.acquire_write(str(file_path))

        try:
            request = AsyncDeleteRequest(path=str(file_path), timeout=0.1)
            response = await async_delete(request, path_validator, lock_manager, hash_registry)

            assert response.status == "error"
            assert response.error_code == ErrorCode.LOCK_TIMEOUT
            assert "lock" in response.message.lower()
        finally:
            await lock_manager.release_write(str(file_path), lock_id)
