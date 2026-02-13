"""Tests for async_batch_write tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncBatchWriteRequest, BatchWriteItem, ErrorCode
from async_crud_mcp.tools import async_batch_write


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


class TestAsyncBatchWriteSuccess:
    """Test successful batch write operations."""

    @pytest.mark.asyncio
    async def test_write_multiple_files(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test writing multiple new files in single call."""
        file1 = temp_base_dir / "file1.txt"
        file2 = temp_base_dir / "file2.txt"
        file3 = temp_base_dir / "file3.txt"

        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path=str(file1), content="content 1"),
                BatchWriteItem(path=str(file2), content="content 2"),
                BatchWriteItem(path=str(file3), content="content 3"),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 3
        assert response.summary.failed == 0
        assert response.summary.contention == 0

        # Verify all files were created with correct content
        assert file1.exists()
        assert file1.read_text(encoding='utf-8') == "content 1"
        assert response.results[0].status == "ok"
        assert response.results[0].hash == compute_hash(b"content 1")

        assert file2.exists()
        assert file2.read_text(encoding='utf-8') == "content 2"
        assert response.results[1].status == "ok"

        assert file3.exists()
        assert file3.read_text(encoding='utf-8') == "content 3"
        assert response.results[2].status == "ok"

    @pytest.mark.asyncio
    async def test_write_with_create_dirs(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test writing files with create_dirs=True for nested paths."""
        nested_file = temp_base_dir / "dir1" / "dir2" / "file.txt"
        flat_file = temp_base_dir / "flat.txt"

        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path=str(nested_file), content="nested", create_dirs=True),
                BatchWriteItem(path=str(flat_file), content="flat", create_dirs=False),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.summary.succeeded == 2

        # Verify nested file was created with parent directories
        assert nested_file.exists()
        assert nested_file.read_text(encoding='utf-8') == "nested"
        assert nested_file.parent.exists()

        # Verify flat file was created
        assert flat_file.exists()
        assert flat_file.read_text(encoding='utf-8') == "flat"

    @pytest.mark.asyncio
    async def test_empty_batch(self, path_validator, lock_manager, hash_registry):
        """Test writing empty batch (0 files)."""
        request = AsyncBatchWriteRequest(files=[])

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 0
        assert response.summary.total == 0
        assert response.summary.succeeded == 0
        assert response.summary.failed == 0

    @pytest.mark.asyncio
    async def test_hash_registry_updated(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry is updated for all successfully written files."""
        file1 = temp_base_dir / "reg1.txt"
        file2 = temp_base_dir / "reg2.txt"

        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path=str(file1), content="reg content 1"),
                BatchWriteItem(path=str(file2), content="reg content 2"),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.summary.succeeded == 2

        # Verify hash registry was updated for both files
        assert hash_registry.get(str(file1)) == response.results[0].hash
        assert hash_registry.get(str(file2)) == response.results[1].hash


class TestAsyncBatchWritePartialFailure:
    """Test partial failure scenarios."""

    @pytest.mark.asyncio
    async def test_partial_failure_existing_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test partial failure when one file already exists."""
        existing_file = temp_base_dir / "existing.txt"
        existing_file.write_text("already exists", encoding='utf-8')

        new_file1 = temp_base_dir / "new1.txt"
        new_file2 = temp_base_dir / "new2.txt"

        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path=str(new_file1), content="new 1"),
                BatchWriteItem(path=str(existing_file), content="overwrite attempt"),
                BatchWriteItem(path=str(new_file2), content="new 2"),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 2
        assert response.summary.failed == 1

        # First file succeeds
        assert response.results[0].status == "ok"
        assert new_file1.exists()
        assert new_file1.read_text(encoding='utf-8') == "new 1"

        # Second file fails (already exists)
        assert response.results[1].status == "error"
        assert response.results[1].error_code == ErrorCode.FILE_EXISTS
        assert existing_file.read_text(encoding='utf-8') == "already exists"

        # Third file succeeds
        assert response.results[2].status == "ok"
        assert new_file2.exists()
        assert new_file2.read_text(encoding='utf-8') == "new 2"

    @pytest.mark.asyncio
    async def test_all_files_fail_outside_base(self, path_validator, lock_manager, hash_registry):
        """Test all files fail when paths are outside base directory."""
        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path="/etc/outside1.txt", content="fail 1"),
                BatchWriteItem(path="/tmp/outside2.txt", content="fail 2"),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 2
        assert response.summary.total == 2
        assert response.summary.succeeded == 0
        assert response.summary.failed == 2

        # Both fail with PATH_OUTSIDE_BASE
        assert response.results[0].status == "error"
        assert response.results[0].error_code == ErrorCode.PATH_OUTSIDE_BASE

        assert response.results[1].status == "error"
        assert response.results[1].error_code == ErrorCode.PATH_OUTSIDE_BASE


class TestAsyncBatchWriteEncoding:
    """Test encoding handling in batch writes."""

    @pytest.mark.asyncio
    async def test_mixed_encodings(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test writing files with different encodings."""
        utf8_file = temp_base_dir / "utf8.txt"
        ascii_file = temp_base_dir / "ascii.txt"

        request = AsyncBatchWriteRequest(
            files=[
                BatchWriteItem(path=str(utf8_file), content="UTF-8 content", encoding='utf-8'),
                BatchWriteItem(path=str(ascii_file), content="ASCII content", encoding='ascii'),
            ]
        )

        response = await async_batch_write(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.summary.succeeded == 2

        # Verify files were created with correct encodings
        assert utf8_file.exists()
        assert ascii_file.exists()
        assert response.results[0].status == "ok"
        assert response.results[1].status == "ok"
