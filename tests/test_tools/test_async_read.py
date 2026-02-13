"""Tests for async_read tool."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AsyncReadRequest, ErrorCode
from async_crud_mcp.tools import async_read


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
def sample_file(temp_base_dir):
    """Create a sample file with multiple lines."""
    file_path = temp_base_dir / "sample.txt"
    # Write in binary mode to ensure Unix line endings
    content = b"line 1\nline 2\nline 3\nline 4\nline 5\n"
    file_path.write_bytes(content)
    return file_path


@pytest.fixture
def empty_file(temp_base_dir):
    """Create an empty file."""
    file_path = temp_base_dir / "empty.txt"
    file_path.write_text("", encoding='utf-8')
    return file_path


@pytest.fixture
def single_line_file(temp_base_dir):
    """Create a single-line file."""
    file_path = temp_base_dir / "single.txt"
    file_path.write_text("single line", encoding='utf-8')
    return file_path


class TestAsyncReadSuccess:
    """Test successful read operations."""

    @pytest.mark.asyncio
    async def test_read_full_content(self, sample_file, path_validator, lock_manager):
        """Test reading entire file without offset/limit."""
        request = AsyncReadRequest(path=str(sample_file))
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == "line 1\nline 2\nline 3\nline 4\nline 5\n"
        assert response.total_lines == 5
        assert response.offset == 0
        assert response.limit is None
        assert response.lines_returned == 5
        assert response.encoding == "utf-8"
        assert response.hash.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_read_with_offset_only(self, sample_file, path_validator, lock_manager):
        """Test reading with offset (skip first N lines)."""
        request = AsyncReadRequest(path=str(sample_file), offset=2)
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == "line 3\nline 4\nline 5\n"
        assert response.total_lines == 5
        assert response.offset == 2
        assert response.limit is None
        assert response.lines_returned == 3

    @pytest.mark.asyncio
    async def test_read_with_limit_only(self, sample_file, path_validator, lock_manager):
        """Test reading with limit (first N lines)."""
        request = AsyncReadRequest(path=str(sample_file), limit=2)
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == "line 1\nline 2\n"
        assert response.total_lines == 5
        assert response.offset == 0
        assert response.limit == 2
        assert response.lines_returned == 2

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, sample_file, path_validator, lock_manager):
        """Test reading with both offset and limit."""
        request = AsyncReadRequest(path=str(sample_file), offset=1, limit=2)
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == "line 2\nline 3\n"
        assert response.total_lines == 5
        assert response.offset == 1
        assert response.limit == 2
        assert response.lines_returned == 2

    @pytest.mark.asyncio
    async def test_hash_is_of_full_content(self, sample_file, path_validator, lock_manager):
        """Test hash is always of full file content regardless of offset/limit."""
        full_content = sample_file.read_bytes()
        expected_hash = compute_hash(full_content)

        # Read with offset/limit
        request = AsyncReadRequest(path=str(sample_file), offset=1, limit=2)
        response = await async_read(request, path_validator, lock_manager)

        # Hash should match full file
        assert response.hash == expected_hash

    @pytest.mark.asyncio
    async def test_read_empty_file(self, empty_file, path_validator, lock_manager):
        """Test reading empty file returns empty content with correct hash."""
        request = AsyncReadRequest(path=str(empty_file))
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == ""
        assert response.total_lines == 0
        assert response.lines_returned == 0
        assert response.hash == compute_hash(b"")

    @pytest.mark.asyncio
    async def test_read_single_line_file(self, single_line_file, path_validator, lock_manager):
        """Test reading single-line file edge case."""
        request = AsyncReadRequest(path=str(single_line_file))
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "ok"
        assert response.content == "single line"
        assert response.total_lines == 1
        assert response.lines_returned == 1


class TestAsyncReadErrors:
    """Test error handling in read operations."""

    @pytest.mark.asyncio
    async def test_file_not_found(self, temp_base_dir, path_validator, lock_manager):
        """Test FILE_NOT_FOUND error for non-existent file."""
        non_existent = temp_base_dir / "does_not_exist.txt"
        request = AsyncReadRequest(path=str(non_existent))
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND
        assert "not found" in response.message.lower()

    @pytest.mark.asyncio
    async def test_path_outside_base(self, path_validator, lock_manager):
        """Test PATH_OUTSIDE_BASE error for path outside base directories."""
        outside_path = "/tmp/outside_base.txt"
        request = AsyncReadRequest(path=outside_path)
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_encoding_error(self, temp_base_dir, path_validator, lock_manager):
        """Test ENCODING_ERROR for files with wrong encoding specified."""
        # Create file with UTF-8 content including special characters
        file_path = temp_base_dir / "utf8.txt"
        file_path.write_bytes("Hello \xc3\xa9".encode('utf-8'))  # "Hello é"

        # Try to read as ASCII (should fail)
        request = AsyncReadRequest(path=str(file_path), encoding='ascii')
        response = await async_read(request, path_validator, lock_manager)

        assert response.status == "error"
        assert response.error_code == ErrorCode.ENCODING_ERROR


class TestAsyncReadConcurrency:
    """Test concurrent read operations."""

    @pytest.mark.asyncio
    async def test_concurrent_reads_allowed(self, sample_file, path_validator, lock_manager):
        """Test concurrent reads don't block each other."""
        request = AsyncReadRequest(path=str(sample_file))

        # Launch 5 concurrent reads
        tasks = [async_read(request, path_validator, lock_manager) for _ in range(5)]
        responses = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.status == "ok" for r in responses)
        assert all(r.content == "line 1\nline 2\nline 3\nline 4\nline 5\n" for r in responses)

    @pytest.mark.asyncio
    async def test_read_blocks_behind_write_lock(self, sample_file, path_validator, lock_manager):
        """Test read blocks behind active write lock."""
        # Acquire write lock manually
        write_request_id = await lock_manager.acquire_write(str(sample_file), timeout=5.0)

        try:
            # Try to read (should timeout)
            request = AsyncReadRequest(path=str(sample_file))
            read_task = asyncio.create_task(async_read(request, path_validator, lock_manager))

            # Wait a bit to ensure read is blocked
            await asyncio.sleep(0.1)

            # Read should still be pending
            assert not read_task.done()

            # Release write lock
            await lock_manager.release_write(str(sample_file), write_request_id)

            # Now read should complete
            response = await asyncio.wait_for(read_task, timeout=1.0)
            assert response.status == "ok"

        except asyncio.TimeoutError:
            await lock_manager.release_write(str(sample_file), write_request_id)
            raise
