"""Tests for async_batch_update tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncBatchUpdateRequest, BatchUpdateItem, ErrorCode, Patch
from async_crud_mcp.tools import async_batch_update


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


def create_file_with_hash(file_path: Path, content: str) -> str:
    """Helper to create a file and return its hash."""
    encoded_bytes = content.encode('utf-8')
    file_path.write_bytes(encoded_bytes)
    return compute_hash(encoded_bytes)


class TestAsyncBatchUpdateSuccess:
    """Test successful batch update operations."""

    @pytest.mark.asyncio
    async def test_update_multiple_files_content_mode(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test updating multiple files with correct expected_hash (content mode)."""
        file1 = temp_base_dir / "file1.txt"
        file2 = temp_base_dir / "file2.txt"
        file3 = temp_base_dir / "file3.txt"

        hash1 = create_file_with_hash(file1, "original 1")
        hash2 = create_file_with_hash(file2, "original 2")
        hash3 = create_file_with_hash(file3, "original 3")

        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(path=str(file1), expected_hash=hash1, content="updated 1"),
                BatchUpdateItem(path=str(file2), expected_hash=hash2, content="updated 2"),
                BatchUpdateItem(path=str(file3), expected_hash=hash3, content="updated 3"),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 3
        assert response.summary.failed == 0
        assert response.summary.contention == 0

        # Verify all files were updated
        assert file1.read_text(encoding='utf-8') == "updated 1"
        assert file2.read_text(encoding='utf-8') == "updated 2"
        assert file3.read_text(encoding='utf-8') == "updated 3"

        # Verify all results are successful
        assert response.results[0].status == "ok"
        assert response.results[1].status == "ok"
        assert response.results[2].status == "ok"

    @pytest.mark.asyncio
    async def test_update_multiple_files_patch_mode(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test updating multiple files with patches mode."""
        file1 = temp_base_dir / "patch1.txt"
        file2 = temp_base_dir / "patch2.txt"

        hash1 = create_file_with_hash(file1, "Hello World")
        hash2 = create_file_with_hash(file2, "foo bar")

        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(
                    path=str(file1),
                    expected_hash=hash1,
                    patches=[Patch(old_string="World", new_string="Universe")]
                ),
                BatchUpdateItem(
                    path=str(file2),
                    expected_hash=hash2,
                    patches=[Patch(old_string="foo", new_string="baz")]
                ),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.summary.succeeded == 2
        assert response.summary.contention == 0

        # Verify patches were applied
        assert file1.read_text(encoding='utf-8') == "Hello Universe"
        assert file2.read_text(encoding='utf-8') == "baz bar"

    @pytest.mark.asyncio
    async def test_empty_batch(self, path_validator, lock_manager, hash_registry):
        """Test updating empty batch (0 files)."""
        request = AsyncBatchUpdateRequest(files=[])

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 0
        assert response.summary.total == 0
        assert response.summary.succeeded == 0
        assert response.summary.failed == 0
        assert response.summary.contention == 0


class TestAsyncBatchUpdateContention:
    """Test contention detection and handling."""

    @pytest.mark.asyncio
    async def test_partial_contention_wrong_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test partial contention when one file has wrong expected_hash."""
        file1 = temp_base_dir / "file1.txt"
        file2 = temp_base_dir / "file2.txt"
        file3 = temp_base_dir / "file3.txt"

        hash1 = create_file_with_hash(file1, "original 1")
        hash2 = create_file_with_hash(file2, "original 2")
        hash3 = create_file_with_hash(file3, "original 3")

        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(path=str(file1), expected_hash=hash1, content="updated 1"),
                BatchUpdateItem(path=str(file2), expected_hash=wrong_hash, content="should fail"),
                BatchUpdateItem(path=str(file3), expected_hash=hash3, content="updated 3"),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 2
        assert response.summary.failed == 0
        assert response.summary.contention == 1

        # First file succeeds
        assert response.results[0].status == "ok"
        assert file1.read_text(encoding='utf-8') == "updated 1"

        # Second file has contention
        assert response.results[1].status == "contention"
        assert file2.read_text(encoding='utf-8') == "original 2"  # Unchanged

        # Third file succeeds
        assert response.results[2].status == "ok"
        assert file3.read_text(encoding='utf-8') == "updated 3"

    @pytest.mark.asyncio
    async def test_mixed_results_success_contention_error(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test mixed results with success, contention, and error."""
        existing_file = temp_base_dir / "existing.txt"
        nonexistent_file = temp_base_dir / "nonexistent.txt"
        contention_file = temp_base_dir / "contention.txt"

        existing_hash = create_file_with_hash(existing_file, "exists")
        contention_hash = create_file_with_hash(contention_file, "original")

        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(path=str(existing_file), expected_hash=existing_hash, content="updated"),
                BatchUpdateItem(path=str(contention_file), expected_hash=wrong_hash, content="fail contention"),
                BatchUpdateItem(path=str(nonexistent_file), expected_hash="sha256:abc", content="fail error"),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 1
        assert response.summary.failed == 1
        assert response.summary.contention == 1

        # First file succeeds
        assert response.results[0].status == "ok"

        # Second file has contention
        assert response.results[1].status == "contention"

        # Third file has error (file not found)
        assert response.results[2].status == "error"
        assert response.results[2].error_code == ErrorCode.FILE_NOT_FOUND


class TestAsyncBatchUpdatePartialFailure:
    """Test partial failure scenarios."""

    @pytest.mark.asyncio
    async def test_all_files_fail_outside_base(self, path_validator, lock_manager, hash_registry):
        """Test all files fail when paths are outside base directory."""
        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(path="/etc/passwd", expected_hash="sha256:abc", content="fail 1"),
                BatchUpdateItem(path="/tmp/outside.txt", expected_hash="sha256:def", content="fail 2"),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert len(response.results) == 2
        assert response.summary.total == 2
        assert response.summary.succeeded == 0
        assert response.summary.failed == 2
        assert response.summary.contention == 0

        # Both fail with PATH_OUTSIDE_BASE
        assert response.results[0].status == "error"
        assert response.results[0].error_code == ErrorCode.PATH_OUTSIDE_BASE

        assert response.results[1].status == "error"
        assert response.results[1].error_code == ErrorCode.PATH_OUTSIDE_BASE


class TestAsyncBatchUpdateHashRegistry:
    """Test HashRegistry updates in batch operations."""

    @pytest.mark.asyncio
    async def test_hash_registry_updated_for_successful_updates(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry is updated only for successfully updated files."""
        file1 = temp_base_dir / "reg1.txt"
        file2 = temp_base_dir / "reg2.txt"

        hash1 = create_file_with_hash(file1, "original 1")
        hash2 = create_file_with_hash(file2, "original 2")

        wrong_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

        request = AsyncBatchUpdateRequest(
            files=[
                BatchUpdateItem(path=str(file1), expected_hash=hash1, content="updated 1"),
                BatchUpdateItem(path=str(file2), expected_hash=wrong_hash, content="fail contention"),
            ]
        )

        response = await async_batch_update(request, path_validator, lock_manager, hash_registry)

        assert response.summary.succeeded == 1
        assert response.summary.contention == 1

        # First file's hash should be updated
        new_hash1 = compute_hash(b"updated 1")
        assert hash_registry.get(str(file1)) == new_hash1

        # Second file's hash should remain unchanged (contention)
        # Note: HashRegistry may not have been initialized, so we just check it wasn't updated to wrong value
        registry_hash2 = hash_registry.get(str(file2))
        assert registry_hash2 != compute_hash(b"fail contention")
