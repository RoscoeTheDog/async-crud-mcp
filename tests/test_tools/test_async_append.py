"""Tests for async_append tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.models import AppendSuccessResponse, AsyncAppendRequest, ErrorCode
from async_crud_mcp.tools import async_append


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


class TestAsyncAppendSuccess:
    """Test successful append operations."""

    @pytest.mark.asyncio
    async def test_append_to_existing_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test append adds content to existing file."""
        file_path = temp_base_dir / "existing.txt"
        original_content = "Line 1\n"
        file_path.write_bytes(original_content.encode('utf-8'))

        append_content = "Line 2\n"
        request = AsyncAppendRequest(path=str(file_path), content=append_content)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.path == str(file_path)
        assert response.bytes_appended == len(append_content.encode('utf-8'))
        assert response.hash.startswith("sha256:")

        # Verify file content (use read_bytes to avoid Windows \r\n translation)
        final_bytes = file_path.read_bytes()
        assert final_bytes == (original_content + append_content).encode('utf-8')

        # Verify total size
        assert response.total_size_bytes == len(final_bytes)

    @pytest.mark.asyncio
    async def test_append_with_separator(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test separator is inserted before content when file is not empty."""
        file_path = temp_base_dir / "separator_test.txt"
        original_content = "First line"
        file_path.write_text(original_content, encoding='utf-8')

        append_content = "Second line"
        separator = "\n"
        request = AsyncAppendRequest(path=str(file_path), content=append_content, separator=separator)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify separator was added
        final_content = file_path.read_text(encoding='utf-8')
        assert final_content == original_content + separator + append_content

    @pytest.mark.asyncio
    async def test_append_updates_hash_registry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test HashRegistry is updated after successful append."""
        file_path = temp_base_dir / "hash_test.txt"
        file_path.write_text("Original", encoding='utf-8')

        request = AsyncAppendRequest(path=str(file_path), content=" Appended")
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify hash registry was updated
        registered_hash = hash_registry.get(str(file_path))
        assert registered_hash == response.hash


class TestAsyncAppendCreateIfMissing:
    """Test create_if_missing behavior."""

    @pytest.mark.asyncio
    async def test_append_creates_file_when_missing(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_if_missing=True creates file if it doesn't exist."""
        file_path = temp_base_dir / "new_file.txt"
        content = "First content"

        request = AsyncAppendRequest(path=str(file_path), content=content, create_if_missing=True)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.exists()
        assert file_path.read_text(encoding='utf-8') == content

    @pytest.mark.asyncio
    async def test_append_error_when_missing_and_no_create(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_if_missing=False returns error when file doesn't exist."""
        file_path = temp_base_dir / "nonexistent.txt"

        request = AsyncAppendRequest(path=str(file_path), content="content", create_if_missing=False)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND


class TestAsyncAppendCreateDirs:
    """Test create_dirs behavior."""

    @pytest.mark.asyncio
    async def test_append_creates_parent_dirs(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test create_dirs=True creates parent directories."""
        file_path = temp_base_dir / "subdir1" / "subdir2" / "file.txt"
        content = "Test content"

        request = AsyncAppendRequest(
            path=str(file_path),
            content=content,
            create_if_missing=True,
            create_dirs=True
        )
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.exists()
        assert file_path.parent.exists()


class TestAsyncAppendSeparator:
    """Test separator handling."""

    @pytest.mark.asyncio
    async def test_separator_skipped_on_empty_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test separator is NOT prepended when file is empty."""
        file_path = temp_base_dir / "empty.txt"
        file_path.write_text("", encoding='utf-8')  # Create empty file

        content = "First line"
        separator = "\n---\n"
        request = AsyncAppendRequest(path=str(file_path), content=content, separator=separator)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify separator was NOT added (file was empty)
        final_content = file_path.read_text(encoding='utf-8')
        assert final_content == content
        assert not final_content.startswith(separator)

    @pytest.mark.asyncio
    async def test_separator_added_on_non_empty_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test separator IS prepended when file is not empty."""
        file_path = temp_base_dir / "non_empty.txt"
        file_path.write_text("Existing content", encoding='utf-8')

        content = "New content"
        separator = "\n---\n"
        request = AsyncAppendRequest(path=str(file_path), content=content, separator=separator)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify separator was added
        final_content = file_path.read_text(encoding='utf-8')
        assert separator in final_content
        assert final_content == "Existing content" + separator + content

    @pytest.mark.asyncio
    async def test_no_separator_when_empty_string(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test empty separator adds no separator."""
        file_path = temp_base_dir / "no_sep.txt"
        file_path.write_text("Content1", encoding='utf-8')

        content = "Content2"
        request = AsyncAppendRequest(path=str(file_path), content=content, separator="")
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"

        # Verify no separator (direct concatenation)
        final_content = file_path.read_text(encoding='utf-8')
        assert final_content == "Content1Content2"


class TestAsyncAppendErrors:
    """Test error handling in append operations."""

    @pytest.mark.asyncio
    async def test_append_path_outside_base(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test append returns PATH_OUTSIDE_BASE when path is outside allowed directories."""
        outside_path = "/etc/passwd"
        request = AsyncAppendRequest(path=outside_path, content="malicious content")

        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_append_lock_timeout(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test append returns LOCK_TIMEOUT when lock cannot be acquired."""
        file_path = temp_base_dir / "locked.txt"
        file_path.write_text("content", encoding='utf-8')

        # Pre-acquire write lock
        lock_id = await lock_manager.acquire_write(str(file_path))

        try:
            request = AsyncAppendRequest(path=str(file_path), content="more content", timeout=0.1)
            response = await async_append(request, path_validator, lock_manager, hash_registry)

            assert response.status == "error"
            assert response.error_code == ErrorCode.LOCK_TIMEOUT
        finally:
            await lock_manager.release_write(str(file_path), lock_id)

    @pytest.mark.asyncio
    async def test_append_encoding_error(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test append returns ENCODING_ERROR on invalid encoding."""
        file_path = temp_base_dir / "encoding_test.txt"
        file_path.write_text("content", encoding='utf-8')

        # Use invalid encoding
        request = AsyncAppendRequest(path=str(file_path), content="test", encoding="invalid-encoding")
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.ENCODING_ERROR


class TestAsyncAppendBytesAppended:
    """Test bytes_appended calculation."""

    @pytest.mark.asyncio
    async def test_bytes_appended_without_separator(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test bytes_appended reflects actual bytes written without separator."""
        file_path = temp_base_dir / "bytes_test.txt"
        file_path.write_text("", encoding='utf-8')  # Empty file

        content = "12345"
        request = AsyncAppendRequest(path=str(file_path), content=content)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.bytes_appended == len(content.encode('utf-8'))

    @pytest.mark.asyncio
    async def test_bytes_appended_with_separator(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test bytes_appended includes separator when added."""
        file_path = temp_base_dir / "bytes_sep_test.txt"
        file_path.write_text("Existing", encoding='utf-8')

        content = "12345"
        separator = "\n"
        request = AsyncAppendRequest(path=str(file_path), content=content, separator=separator)
        response = await async_append(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        # bytes_appended should include separator
        expected_bytes = len((separator + content).encode('utf-8'))
        assert response.bytes_appended == expected_bytes
