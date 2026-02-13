"""Tests for async_list tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, PathValidator
from async_crud_mcp.models import AsyncListRequest, ErrorCode
from async_crud_mcp.tools import async_list


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
def hash_registry():
    """Create HashRegistry instance."""
    return HashRegistry()


@pytest.fixture
def sample_dir_with_files(temp_base_dir):
    """Create a directory with various files."""
    # Create files
    (temp_base_dir / "file1.txt").write_text("content1", encoding='utf-8')
    (temp_base_dir / "file2.py").write_text("print('hello')", encoding='utf-8')
    (temp_base_dir / "file3.md").write_text("# Title", encoding='utf-8')

    # Create subdirectory with files
    subdir = temp_base_dir / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested content", encoding='utf-8')
    (subdir / "nested.py").write_text("print('nested')", encoding='utf-8')

    return temp_base_dir


@pytest.fixture
def empty_dir(temp_base_dir):
    """Create an empty directory."""
    empty = temp_base_dir / "empty"
    empty.mkdir()
    return empty


class TestAsyncListBasic:
    """Test basic list operations."""

    @pytest.mark.asyncio
    async def test_list_basic(self, sample_dir_with_files, path_validator, hash_registry):
        """Test basic directory listing without filters."""
        request = AsyncListRequest(path=str(sample_dir_with_files))
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.path == str(sample_dir_with_files)
        assert response.pattern == "*"
        assert response.recursive is False
        assert response.total_entries == 4  # 3 files + 1 directory

        # Check entries
        entry_names = {entry.name for entry in response.entries}
        assert "file1.txt" in entry_names
        assert "file2.py" in entry_names
        assert "file3.md" in entry_names
        assert "subdir" in entry_names

        # Verify types
        for entry in response.entries:
            if entry.name == "subdir":
                assert entry.type == "directory"
                assert entry.size_bytes is None
            else:
                assert entry.type == "file"
                assert entry.size_bytes is not None
                assert entry.size_bytes > 0

    @pytest.mark.asyncio
    async def test_list_empty_dir(self, empty_dir, path_validator, hash_registry):
        """Test listing empty directory."""
        request = AsyncListRequest(path=str(empty_dir))
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.total_entries == 0
        assert len(response.entries) == 0


class TestAsyncListGlobPattern:
    """Test glob pattern filtering."""

    @pytest.mark.asyncio
    async def test_list_glob_pattern_py(self, sample_dir_with_files, path_validator, hash_registry):
        """Test filtering with *.py pattern."""
        request = AsyncListRequest(path=str(sample_dir_with_files), pattern="*.py")
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.pattern == "*.py"
        assert response.total_entries == 1

        entry_names = {entry.name for entry in response.entries}
        assert "file2.py" in entry_names
        assert "file1.txt" not in entry_names
        assert "file3.md" not in entry_names

    @pytest.mark.asyncio
    async def test_list_glob_pattern_txt(self, sample_dir_with_files, path_validator, hash_registry):
        """Test filtering with *.txt pattern."""
        request = AsyncListRequest(path=str(sample_dir_with_files), pattern="*.txt")
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.total_entries == 1

        entry_names = {entry.name for entry in response.entries}
        assert "file1.txt" in entry_names

    @pytest.mark.asyncio
    async def test_list_glob_pattern_wildcard(self, sample_dir_with_files, path_validator, hash_registry):
        """Test filtering with file* pattern."""
        request = AsyncListRequest(path=str(sample_dir_with_files), pattern="file*")
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.total_entries == 3  # file1.txt, file2.py, file3.md

        entry_names = {entry.name for entry in response.entries}
        assert "file1.txt" in entry_names
        assert "file2.py" in entry_names
        assert "file3.md" in entry_names
        assert "subdir" not in entry_names


class TestAsyncListRecursive:
    """Test recursive listing."""

    @pytest.mark.asyncio
    async def test_list_recursive(self, sample_dir_with_files, path_validator, hash_registry):
        """Test recursive directory listing."""
        request = AsyncListRequest(path=str(sample_dir_with_files), recursive=True)
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.recursive is True
        # 3 top-level files + 1 subdir + 2 nested files = 6 total
        assert response.total_entries == 6

        entry_names = {entry.name for entry in response.entries}
        assert "file1.txt" in entry_names
        assert "file2.py" in entry_names
        assert "file3.md" in entry_names
        assert "subdir" in entry_names
        # Nested files should have relative paths
        assert any("subdir" in name and "nested.txt" in name for name in entry_names)
        assert any("subdir" in name and "nested.py" in name for name in entry_names)

    @pytest.mark.asyncio
    async def test_list_recursive_with_pattern(self, sample_dir_with_files, path_validator, hash_registry):
        """Test recursive listing with glob pattern."""
        request = AsyncListRequest(
            path=str(sample_dir_with_files),
            pattern="*.py",
            recursive=True
        )
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"
        assert response.recursive is True
        assert response.pattern == "*.py"
        assert response.total_entries == 2  # file2.py + nested.py

        entry_names = {entry.name for entry in response.entries}
        # Should include both top-level and nested .py files
        assert "file2.py" in entry_names
        assert any("nested.py" in name for name in entry_names)


class TestAsyncListIncludeHashes:
    """Test include_hashes functionality."""

    @pytest.mark.asyncio
    async def test_list_include_hashes_tracked(self, sample_dir_with_files, path_validator, hash_registry):
        """Test listing with include_hashes for tracked files."""
        # Pre-populate hash registry
        file1_path = sample_dir_with_files / "file1.txt"
        file2_path = sample_dir_with_files / "file2.py"
        hash_registry.update(str(file1_path), "sha256:abc123")
        hash_registry.update(str(file2_path), "sha256:def456")

        request = AsyncListRequest(
            path=str(sample_dir_with_files),
            include_hashes=True
        )
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"

        # Check hashes are attached for tracked files
        for entry in response.entries:
            if entry.name == "file1.txt":
                assert entry.hash == "sha256:abc123"
            elif entry.name == "file2.py":
                assert entry.hash == "sha256:def456"
            elif entry.name == "file3.md":
                # Not in registry, should be None
                assert entry.hash is None
            elif entry.name == "subdir":
                # Directories don't have hashes
                assert entry.hash is None

    @pytest.mark.asyncio
    async def test_list_include_hashes_untracked(self, sample_dir_with_files, path_validator, hash_registry):
        """Test listing with include_hashes for untracked files."""
        request = AsyncListRequest(
            path=str(sample_dir_with_files),
            include_hashes=True
        )
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"

        # All files should have None hash since registry is empty
        for entry in response.entries:
            if entry.type == "file":
                assert entry.hash is None

    @pytest.mark.asyncio
    async def test_list_without_include_hashes(self, sample_dir_with_files, path_validator, hash_registry):
        """Test listing without include_hashes (default behavior)."""
        # Pre-populate hash registry
        file1_path = sample_dir_with_files / "file1.txt"
        hash_registry.update(str(file1_path), "sha256:abc123")

        request = AsyncListRequest(
            path=str(sample_dir_with_files),
            include_hashes=False
        )
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "ok"

        # Hashes should not be attached even though file is tracked
        for entry in response.entries:
            assert entry.hash is None


class TestAsyncListErrors:
    """Test error conditions."""

    @pytest.mark.asyncio
    async def test_list_dir_not_found(self, temp_base_dir, path_validator, hash_registry):
        """Test listing non-existent directory."""
        nonexistent = temp_base_dir / "nonexistent"
        request = AsyncListRequest(path=str(nonexistent))
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.DIR_NOT_FOUND
        assert "not found" in response.message.lower()

    @pytest.mark.asyncio
    async def test_list_path_is_file(self, sample_dir_with_files, path_validator, hash_registry):
        """Test listing a file instead of directory."""
        file_path = sample_dir_with_files / "file1.txt"
        request = AsyncListRequest(path=str(file_path))
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.DIR_NOT_FOUND
        assert "not a directory" in response.message.lower()

    @pytest.mark.asyncio
    async def test_list_path_outside_base(self, path_validator, hash_registry):
        """Test listing path outside base directory."""
        outside_path = "/tmp/outside"
        request = AsyncListRequest(path=outside_path)
        response = await async_list(request, path_validator, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE
