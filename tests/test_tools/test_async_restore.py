"""Tests for async_restore tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, RecycleBin, compute_hash
from async_crud_mcp.models import AsyncDeleteRequest, AsyncRestoreRequest, ErrorCode
from async_crud_mcp.tools import async_delete, async_restore


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
def recycle_bin(temp_base_dir):
    """Create RecycleBin with temp recycle directory."""
    recycle_dir = temp_base_dir / ".recycle"
    return RecycleBin(
        project_recycle_dir=recycle_dir,
        global_recycle_dir=temp_base_dir / ".global_recycle",
        enabled=True,
        retention_days=90,
    )


class TestAsyncRestoreSuccess:
    """Test successful restore operations."""

    @pytest.mark.asyncio
    async def test_restore_success(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Delete then restore roundtrip."""
        file_path = temp_base_dir / "restore_me.txt"
        content = "This will be restored"
        file_path.write_text(content, encoding="utf-8")

        # Delete the file (moves to recycle bin)
        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )
        assert del_response.status == "ok"
        assert del_response.recycled is True
        assert del_response.recycle_name is not None
        assert not file_path.exists()

        # Restore the file
        restore_request = AsyncRestoreRequest(recycle_name=del_response.recycle_name)
        response = await async_restore(restore_request, path_validator, recycle_bin)

        assert response.status == "ok"
        assert response.restored_path == str(file_path)
        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == content

    @pytest.mark.asyncio
    async def test_restore_with_force(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Overwrite when force=True."""
        file_path = temp_base_dir / "force_test.txt"
        file_path.write_text("original", encoding="utf-8")

        # Delete
        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )

        # Create blocking file at same path
        file_path.write_text("blocking", encoding="utf-8")

        # Restore with force
        restore_request = AsyncRestoreRequest(
            recycle_name=del_response.recycle_name, force=True
        )
        response = await async_restore(restore_request, path_validator, recycle_bin)

        assert response.status == "ok"
        assert file_path.read_text(encoding="utf-8") == "original"


class TestAsyncRestoreErrors:
    """Test error handling in restore operations."""

    @pytest.mark.asyncio
    async def test_restore_file_not_found(self, path_validator, recycle_bin):
        """ErrorResponse for unknown recycle name."""
        request = AsyncRestoreRequest(recycle_name="nonexistent_20260101_000000_file.txt")
        response = await async_restore(request, path_validator, recycle_bin)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_restore_destination_conflict(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """ErrorResponse when destination exists and force=False."""
        file_path = temp_base_dir / "conflict.txt"
        file_path.write_text("original", encoding="utf-8")

        # Delete
        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )

        # Create blocking file
        file_path.write_text("blocking", encoding="utf-8")

        # Try restore without force
        restore_request = AsyncRestoreRequest(recycle_name=del_response.recycle_name)
        response = await async_restore(restore_request, path_validator, recycle_bin)

        assert response.status == "error"
        # File still has blocking content
        assert file_path.read_text(encoding="utf-8") == "blocking"

    @pytest.mark.asyncio
    async def test_restore_validates_destination_path(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Path validation on custom destination."""
        file_path = temp_base_dir / "valid_file.txt"
        file_path.write_text("data", encoding="utf-8")

        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )

        # Try restoring to path outside base directory
        restore_request = AsyncRestoreRequest(
            recycle_name=del_response.recycle_name,
            destination="/etc/unauthorized/restored.txt",
        )
        response = await async_restore(restore_request, path_validator, recycle_bin)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE
