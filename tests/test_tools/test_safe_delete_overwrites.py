"""Tests for safe-delete before destructive overwrites.

Tests that mkdir(force=True), rename(overwrite=True), and restore(force=True)
all recycle existing content instead of permanently destroying it.
"""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, RecycleBin, compute_hash
from async_crud_mcp.models import (
    AsyncDeleteRequest,
    AsyncMkdirRequest,
    AsyncRenameRequest,
    AsyncRestoreRequest,
    ErrorCode,
)
from async_crud_mcp.tools import async_delete, async_mkdir, async_rename, async_restore


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


class TestMkdirForceRecycles:
    """Test mkdir force=True recycles non-empty directories."""

    @pytest.mark.asyncio
    async def test_mkdir_force_recycles_nonempty_dir(self, temp_base_dir, path_validator, recycle_bin):
        """Verify dir contents go to recycle bin when force=True."""
        target_dir = temp_base_dir / "mydir"
        target_dir.mkdir()
        (target_dir / "file1.txt").write_text("content1", encoding="utf-8")
        (target_dir / "file2.txt").write_text("content2", encoding="utf-8")

        request = AsyncMkdirRequest(path=str(target_dir), force=True)
        response = await async_mkdir(request, path_validator, recycle_bin)

        assert response.status == "ok"
        assert response.created is True
        # Directory should exist but be empty
        assert target_dir.exists()
        assert len(list(target_dir.iterdir())) == 0

        # Verify recycled contents exist in recycle bin
        entries = await recycle_bin.list_entries()
        assert len(entries) == 1
        assert entries[0].reason == "mkdir-force"
        assert "dir:2_entries" == entries[0].deleted_hash

    @pytest.mark.asyncio
    async def test_mkdir_force_empty_dir_no_recycle(self, temp_base_dir, path_validator, recycle_bin):
        """Empty dir with force=True returns created=False, no recycling."""
        target_dir = temp_base_dir / "emptydir"
        target_dir.mkdir()

        request = AsyncMkdirRequest(path=str(target_dir), force=True)
        response = await async_mkdir(request, path_validator, recycle_bin)

        assert response.status == "ok"
        assert response.created is False

        entries = await recycle_bin.list_entries()
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_mkdir_force_without_recycle_bin_errors(self, temp_base_dir, path_validator):
        """Verify error when no recycle bin available for force mkdir."""
        target_dir = temp_base_dir / "norecycle"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("data", encoding="utf-8")

        request = AsyncMkdirRequest(path=str(target_dir), force=True)
        response = await async_mkdir(request, path_validator, recycle_bin=None)

        assert response.status == "error"
        assert response.error_code == ErrorCode.SERVER_ERROR
        assert "recycle bin" in response.message.lower()

    @pytest.mark.asyncio
    async def test_mkdir_force_disabled_recycle_bin_errors(self, temp_base_dir, path_validator):
        """Verify error when recycle bin is disabled for force mkdir."""
        target_dir = temp_base_dir / "disabled"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("data", encoding="utf-8")

        disabled_bin = RecycleBin(
            project_recycle_dir=temp_base_dir / ".recycle",
            global_recycle_dir=temp_base_dir / ".global_recycle",
            enabled=False,
        )

        request = AsyncMkdirRequest(path=str(target_dir), force=True)
        response = await async_mkdir(request, path_validator, disabled_bin)

        assert response.status == "error"
        assert response.error_code == ErrorCode.SERVER_ERROR

    @pytest.mark.asyncio
    async def test_mkdir_force_on_config_dir_refused(self, temp_base_dir, path_validator, recycle_bin):
        """Verify error when targeting the recycle bin directory."""
        # Create the recycle dir with content
        recycle_dir = recycle_bin.recycle_dir
        recycle_dir.mkdir(parents=True, exist_ok=True)
        (recycle_dir / "dummy.txt").write_text("data", encoding="utf-8")

        # Add recycle dir to path validator's allowed paths
        pv = PathValidator(base_directories=[str(temp_base_dir)])

        request = AsyncMkdirRequest(path=str(recycle_dir), force=True)
        response = await async_mkdir(request, pv, recycle_bin)

        assert response.status == "error"
        assert response.error_code == ErrorCode.ACCESS_DENIED
        assert "configuration" in response.message.lower()


class TestRenameOverwriteRecycles:
    """Test rename overwrite=True recycles destination."""

    @pytest.mark.asyncio
    async def test_rename_overwrite_recycles_destination(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Verify dest file is recycled before rename."""
        src = temp_base_dir / "source.txt"
        dst = temp_base_dir / "destination.txt"
        src.write_text("new content", encoding="utf-8")
        dst.write_text("old content to recycle", encoding="utf-8")

        request = AsyncRenameRequest(old_path=str(src), new_path=str(dst), overwrite=True)
        response = await async_rename(request, path_validator, lock_manager, hash_registry, recycle_bin)

        assert response.status == "ok"
        assert dst.read_text(encoding="utf-8") == "new content"

        # Verify old destination was recycled
        entries = await recycle_bin.list_entries()
        assert len(entries) == 1
        assert entries[0].reason == "rename-overwrite"
        assert entries[0].original_path == str(dst)

    @pytest.mark.asyncio
    async def test_rename_overwrite_without_recycle_bin_errors(
        self, temp_base_dir, path_validator, lock_manager, hash_registry
    ):
        """Verify error when no recycle bin for overwrite rename."""
        src = temp_base_dir / "src.txt"
        dst = temp_base_dir / "dst.txt"
        src.write_text("source", encoding="utf-8")
        dst.write_text("destination", encoding="utf-8")

        request = AsyncRenameRequest(old_path=str(src), new_path=str(dst), overwrite=True)
        response = await async_rename(request, path_validator, lock_manager, hash_registry, recycle_bin=None)

        assert response.status == "error"
        assert response.error_code == ErrorCode.SERVER_ERROR
        # Both files should remain unchanged
        assert src.exists()
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == "destination"

    @pytest.mark.asyncio
    async def test_rename_no_overwrite_no_recycle_bin_ok(
        self, temp_base_dir, path_validator, lock_manager, hash_registry
    ):
        """Without overwrite, rename works fine without recycle_bin."""
        src = temp_base_dir / "src.txt"
        dst = temp_base_dir / "dst_new.txt"
        src.write_text("content", encoding="utf-8")

        request = AsyncRenameRequest(old_path=str(src), new_path=str(dst))
        response = await async_rename(request, path_validator, lock_manager, hash_registry, recycle_bin=None)

        assert response.status == "ok"
        assert dst.read_text(encoding="utf-8") == "content"

    @pytest.mark.asyncio
    async def test_rename_overwrite_into_recycle_dir_refused(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Verify error when dest is inside recycle bin directory."""
        src = temp_base_dir / "source.txt"
        src.write_text("data", encoding="utf-8")

        # Create a file inside the recycle dir
        recycle_bin.recycle_dir.mkdir(parents=True, exist_ok=True)
        dst = recycle_bin.recycle_dir / "target.txt"
        dst.write_text("existing", encoding="utf-8")

        # Need to allow recycle dir in path validator
        pv = PathValidator(base_directories=[str(temp_base_dir)])

        request = AsyncRenameRequest(old_path=str(src), new_path=str(dst), overwrite=True)
        response = await async_rename(request, pv, lock_manager, hash_registry, recycle_bin)

        assert response.status == "error"
        assert response.error_code == ErrorCode.ACCESS_DENIED


class TestRestoreForceRecycles:
    """Test restore force=True recycles existing file at destination."""

    @pytest.mark.asyncio
    async def test_restore_force_recycles_existing(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Verify existing file is recycled before restore overwrites it."""
        file_path = temp_base_dir / "my_file.txt"
        file_path.write_text("original content", encoding="utf-8")

        # Delete the file (moves to recycle bin)
        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )
        assert del_response.status == "ok"

        # Create a new file at the same path (blocking file)
        file_path.write_text("blocking content", encoding="utf-8")

        # Restore with force - should recycle "blocking content" first
        restore_request = AsyncRestoreRequest(
            recycle_name=del_response.recycle_name, force=True
        )
        response = await async_restore(restore_request, path_validator, recycle_bin)

        assert response.status == "ok"
        assert file_path.read_text(encoding="utf-8") == "original content"

        # Verify the blocking file was recycled (not permanently destroyed)
        entries = await recycle_bin.list_entries()
        # Should have the "overwritten-by-restore" entry
        overwrite_entries = [e for e in entries if e.reason == "overwritten-by-restore"]
        assert len(overwrite_entries) == 1
        assert overwrite_entries[0].original_path == str(file_path)

    @pytest.mark.asyncio
    async def test_restore_force_into_recycle_dir_refused(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, recycle_bin
    ):
        """Verify error when restoring into recycle bin directory."""
        file_path = temp_base_dir / "recycle_test.txt"
        file_path.write_text("data", encoding="utf-8")

        # Delete the file
        del_request = AsyncDeleteRequest(path=str(file_path))
        del_response = await async_delete(
            del_request, path_validator, lock_manager, hash_registry, recycle_bin
        )
        assert del_response.status == "ok"

        # Try restoring into recycle dir itself
        dest_in_recycle = recycle_bin.recycle_dir / "bad_dest.txt"
        pv = PathValidator(base_directories=[str(temp_base_dir)])

        restore_request = AsyncRestoreRequest(
            recycle_name=del_response.recycle_name,
            destination=str(dest_in_recycle),
            force=True,
        )
        response = await async_restore(restore_request, pv, recycle_bin)

        assert response.status == "error"


class TestIsProtectedPath:
    """Test RecycleBin.is_protected_path method."""

    def test_recycle_dir_is_protected(self, temp_base_dir, recycle_bin):
        """Recycle dir itself is protected."""
        recycle_bin.recycle_dir.mkdir(parents=True, exist_ok=True)
        assert recycle_bin.is_protected_path(recycle_bin.recycle_dir) is True

    def test_file_inside_recycle_dir_is_protected(self, temp_base_dir, recycle_bin):
        """Files inside recycle dir are protected."""
        recycle_bin.recycle_dir.mkdir(parents=True, exist_ok=True)
        inner = recycle_bin.recycle_dir / "somefile.txt"
        inner.touch()
        assert recycle_bin.is_protected_path(inner) is True

    def test_sibling_path_not_protected(self, temp_base_dir, recycle_bin):
        """Paths outside recycle dir are not protected."""
        recycle_bin.recycle_dir.mkdir(parents=True, exist_ok=True)
        sibling = temp_base_dir / "not_recycle" / "file.txt"
        assert recycle_bin.is_protected_path(sibling) is False

    def test_base_dir_not_protected(self, temp_base_dir, recycle_bin):
        """Base dir itself is not protected."""
        recycle_bin.recycle_dir.mkdir(parents=True, exist_ok=True)
        assert recycle_bin.is_protected_path(temp_base_dir) is False
