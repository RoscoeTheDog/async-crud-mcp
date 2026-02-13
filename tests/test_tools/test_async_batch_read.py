"""Tests for async_batch_read tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import LockManager, PathValidator
from async_crud_mcp.models import AsyncBatchReadRequest, BatchReadItem, ErrorCode
from async_crud_mcp.tools import async_batch_read


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
def sample_files(temp_base_dir):
    """Create multiple sample files for batch operations."""
    files = {}

    # File 1: Simple content (use binary write to ensure Unix line endings)
    file1 = temp_base_dir / "file1.txt"
    file1.write_bytes(b"line 1\nline 2\nline 3\n")
    files['file1'] = file1

    # File 2: Different content
    file2 = temp_base_dir / "file2.txt"
    file2.write_bytes(b"alpha\nbeta\ngamma\ndelta\n")
    files['file2'] = file2

    # File 3: Single line
    file3 = temp_base_dir / "file3.txt"
    file3.write_bytes(b"single line")
    files['file3'] = file3

    return files


class TestAsyncBatchReadSuccess:
    """Test successful batch read operations."""

    @pytest.mark.asyncio
    async def test_read_multiple_files(self, sample_files, path_validator, lock_manager):
        """Test reading multiple files in single call."""
        request = AsyncBatchReadRequest(
            files=[
                BatchReadItem(path=str(sample_files['file1'])),
                BatchReadItem(path=str(sample_files['file2'])),
                BatchReadItem(path=str(sample_files['file3'])),
            ]
        )

        response = await async_batch_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 3
        assert response.summary.failed == 0
        assert response.summary.contention == 0

        # Verify each file's content
        assert response.results[0].status == "ok"
        assert response.results[0].content == "line 1\nline 2\nline 3\n"
        assert response.results[0].total_lines == 3

        assert response.results[1].status == "ok"
        assert response.results[1].content == "alpha\nbeta\ngamma\ndelta\n"
        assert response.results[1].total_lines == 4

        assert response.results[2].status == "ok"
        assert response.results[2].content == "single line"
        assert response.results[2].total_lines == 1

    @pytest.mark.asyncio
    async def test_read_with_offset_limit(self, sample_files, path_validator, lock_manager):
        """Test reading files with offset/limit per file."""
        request = AsyncBatchReadRequest(
            files=[
                BatchReadItem(path=str(sample_files['file1']), offset=1, limit=2),
                BatchReadItem(path=str(sample_files['file2']), offset=0, limit=2),
            ]
        )

        response = await async_batch_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.summary.succeeded == 2

        # File1: offset 1, limit 2 -> lines 2-3
        assert response.results[0].status == "ok"
        assert response.results[0].content == "line 2\nline 3\n"
        assert response.results[0].lines_returned == 2

        # File2: offset 0, limit 2 -> lines 1-2
        assert response.results[1].status == "ok"
        assert response.results[1].content == "alpha\nbeta\n"
        assert response.results[1].lines_returned == 2

    @pytest.mark.asyncio
    async def test_empty_batch(self, path_validator, lock_manager):
        """Test reading empty batch (0 files)."""
        request = AsyncBatchReadRequest(files=[])

        response = await async_batch_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert len(response.results) == 0
        assert response.summary.total == 0
        assert response.summary.succeeded == 0
        assert response.summary.failed == 0


class TestAsyncBatchReadPartialFailure:
    """Test partial failure scenarios."""

    @pytest.mark.asyncio
    async def test_partial_failure_nonexistent_file(self, sample_files, temp_base_dir, path_validator, lock_manager):
        """Test partial failure when one file doesn't exist."""
        nonexistent = temp_base_dir / "nonexistent.txt"

        request = AsyncBatchReadRequest(
            files=[
                BatchReadItem(path=str(sample_files['file1'])),
                BatchReadItem(path=str(nonexistent)),
                BatchReadItem(path=str(sample_files['file2'])),
            ]
        )

        response = await async_batch_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert len(response.results) == 3
        assert response.summary.total == 3
        assert response.summary.succeeded == 2
        assert response.summary.failed == 1

        # First file succeeds
        assert response.results[0].status == "ok"
        assert response.results[0].content == "line 1\nline 2\nline 3\n"

        # Second file fails
        assert response.results[1].status == "error"
        assert response.results[1].error_code == ErrorCode.FILE_NOT_FOUND

        # Third file succeeds
        assert response.results[2].status == "ok"
        assert response.results[2].content == "alpha\nbeta\ngamma\ndelta\n"

    @pytest.mark.asyncio
    async def test_all_files_fail_outside_base(self, sample_files, path_validator, lock_manager):
        """Test all files fail when paths are outside base directory."""
        request = AsyncBatchReadRequest(
            files=[
                BatchReadItem(path="/etc/passwd"),
                BatchReadItem(path="/tmp/outside.txt"),
            ]
        )

        response = await async_batch_read(request, path_validator, lock_manager)

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


class TestAsyncBatchReadEncoding:
    """Test encoding handling in batch reads."""

    @pytest.mark.asyncio
    async def test_mixed_encodings(self, temp_base_dir, path_validator, lock_manager):
        """Test reading files with different encodings."""
        # UTF-8 file
        utf8_file = temp_base_dir / "utf8.txt"
        utf8_file.write_text("Hello World", encoding='utf-8')

        # ASCII file
        ascii_file = temp_base_dir / "ascii.txt"
        ascii_file.write_text("Plain ASCII", encoding='ascii')

        request = AsyncBatchReadRequest(
            files=[
                BatchReadItem(path=str(utf8_file), encoding='utf-8'),
                BatchReadItem(path=str(ascii_file), encoding='ascii'),
            ]
        )

        response = await async_batch_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.summary.succeeded == 2
        assert response.results[0].status == "ok"
        assert response.results[1].status == "ok"
