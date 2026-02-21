"""Tests for async_search tool."""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.config import SearchConfig
from async_crud_mcp.core import ContentScanner, PathValidator
from async_crud_mcp.models.requests import SearchRequest
from async_crud_mcp.models.responses import ErrorCode
from async_crud_mcp.tools.async_search import async_search


@pytest.fixture
def temp_base_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def path_validator(temp_base_dir):
    return PathValidator(base_directories=[str(temp_base_dir)])


@pytest.fixture
def search_config():
    return SearchConfig()


@pytest.fixture
def sample_files(temp_base_dir):
    """Create sample files for search testing."""
    # Python file
    py_file = temp_base_dir / "main.py"
    py_file.write_text("def main():\n    print('hello')\n    return 0\n", encoding="utf-8")

    # Another Python file
    util_file = temp_base_dir / "utils.py"
    util_file.write_text("def helper():\n    pass\n\ndef main_helper():\n    pass\n", encoding="utf-8")

    # Text file
    txt_file = temp_base_dir / "notes.txt"
    txt_file.write_text("This is a note.\nAnother line.\n", encoding="utf-8")

    # Subdirectory with file
    sub_dir = temp_base_dir / "sub"
    sub_dir.mkdir()
    sub_file = sub_dir / "nested.py"
    sub_file.write_text("def nested_func():\n    return 42\n", encoding="utf-8")

    return {"py": py_file, "util": util_file, "txt": txt_file, "nested": sub_file}


class TestAsyncSearchBasic:
    """Test basic search functionality."""

    @pytest.mark.asyncio
    async def test_simple_pattern(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="def main", glob="*.py")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        assert response.total_matches >= 1
        assert any("main" in m.line_content for m in response.matches)

    @pytest.mark.asyncio
    async def test_no_matches(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="nonexistent_pattern_xyz")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        assert response.total_matches == 0
        assert len(response.matches) == 0

    @pytest.mark.asyncio
    async def test_case_insensitive(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="DEF MAIN", case_insensitive=True, glob="*.py")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        assert response.total_matches >= 1

    @pytest.mark.asyncio
    async def test_recursive_search(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="nested_func", recursive=True)
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        assert response.total_matches >= 1

    @pytest.mark.asyncio
    async def test_non_recursive(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="nested_func", recursive=False)
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        assert response.total_matches == 0


class TestAsyncSearchOutputModes:
    """Test different output modes."""

    @pytest.mark.asyncio
    async def test_content_mode(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="def", glob="*.py", output_mode="content")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.output_mode == "content"
        assert all(m.line_content for m in response.matches)

    @pytest.mark.asyncio
    async def test_files_with_matches_mode(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="def", glob="*.py", output_mode="files_with_matches")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.output_mode == "files_with_matches"
        # Should have at most one match per file
        files = [m.file for m in response.matches]
        assert len(files) == len(set(files))

    @pytest.mark.asyncio
    async def test_count_mode(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="def", glob="*.py", output_mode="count")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.output_mode == "count"
        assert response.total_matches > 0
        assert len(response.matches) == 0  # count mode doesn't return match details


class TestAsyncSearchContext:
    """Test context lines."""

    @pytest.mark.asyncio
    async def test_context_lines(self, search_config, path_validator, temp_base_dir, sample_files):
        request = SearchRequest(pattern="print", glob="*.py", context_lines=1)
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "ok"
        # The match for "print('hello')" should have context
        for m in response.matches:
            if "print" in m.line_content:
                # Should have context_before (def main():) and/or context_after
                assert len(m.context_before) > 0 or len(m.context_after) > 0


class TestAsyncSearchErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_disabled(self, path_validator, temp_base_dir):
        config = SearchConfig(enabled=False)
        request = SearchRequest(pattern="test")
        response = await async_search(request, config, path_validator, project_root=temp_base_dir)
        assert response.status == "error"
        assert response.error_code == ErrorCode.SEARCH_DISABLED

    @pytest.mark.asyncio
    async def test_invalid_regex(self, search_config, path_validator, temp_base_dir):
        request = SearchRequest(pattern="[invalid")
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "error"
        assert response.error_code == ErrorCode.INVALID_PATTERN

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, search_config, path_validator, temp_base_dir):
        request = SearchRequest(pattern="test", path=str(temp_base_dir / "nonexistent"))
        response = await async_search(
            request, search_config, path_validator, project_root=temp_base_dir
        )
        assert response.status == "error"
        assert response.error_code == ErrorCode.DIR_NOT_FOUND

    @pytest.mark.asyncio
    async def test_max_results_respected(self, path_validator, temp_base_dir, sample_files):
        config = SearchConfig(max_results=1)
        request = SearchRequest(pattern="def", glob="*.py", max_results=1)
        response = await async_search(
            request, config, path_validator, project_root=temp_base_dir
        )
        assert len(response.matches) <= 1

    @pytest.mark.asyncio
    async def test_no_project_root(self, search_config, path_validator):
        request = SearchRequest(pattern="test")
        response = await async_search(request, search_config, path_validator)
        assert response.status == "error"


class TestAsyncSearchAccessControl:
    """Test access control integration."""

    @pytest.mark.asyncio
    async def test_respects_path_validator(self, search_config, temp_base_dir, sample_files):
        """Files outside base directory should be skipped."""
        # Create validator with a different base
        other_dir = temp_base_dir / "other"
        other_dir.mkdir()
        validator = PathValidator(base_directories=[str(other_dir)])

        request = SearchRequest(pattern="def", glob="*.py")
        response = await async_search(
            request, search_config, validator, project_root=temp_base_dir
        )
        # Files in temp_base_dir are outside 'other' base, so should be skipped
        assert response.files_searched == 0

    @pytest.mark.asyncio
    async def test_large_file_skipped(self, path_validator, temp_base_dir):
        """Files exceeding max_file_size_bytes should be skipped."""
        config = SearchConfig(max_file_size_bytes=10)  # Very small limit
        big_file = temp_base_dir / "big.txt"
        big_file.write_text("x" * 100, encoding="utf-8")

        request = SearchRequest(pattern="x")
        response = await async_search(
            request, config, path_validator, project_root=temp_base_dir
        )
        assert response.total_matches == 0
