"""Tests for PathValidator security and cross-platform path handling."""

import os
import sys
from pathlib import Path

import pytest

from async_crud_mcp.core.path_validator import PathValidationError, PathValidator


class TestBasicValidation:
    """Test basic path validation against base directories."""

    def test_path_inside_base_directory_passes(self, tmp_path):
        """Path inside base directory is allowed."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        validator = PathValidator([str(base_dir)])
        result = validator.validate(str(file_path))

        assert result.is_absolute()
        assert str(result) == str(file_path.resolve())

    def test_path_outside_base_directory_fails(self, tmp_path):
        """Path outside base directory is rejected."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()
        forbidden_file = forbidden_dir / "file.txt"
        forbidden_file.touch()

        validator = PathValidator([str(base_dir)])

        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate(str(forbidden_file))

    def test_path_equal_to_base_directory_passes(self, tmp_path):
        """Path equal to base directory itself is allowed."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()

        validator = PathValidator([str(base_dir)])
        result = validator.validate(str(base_dir))

        assert result.is_absolute()

    def test_path_prefix_but_not_child_fails(self, tmp_path):
        """Path that is a string prefix but not a child directory is rejected."""
        # If base=/foo/bar, then /foo/barbaz should NOT match
        base_dir = tmp_path / "bar"
        base_dir.mkdir()
        similar_dir = tmp_path / "barbaz"
        similar_dir.mkdir()
        file_path = similar_dir / "file.txt"
        file_path.touch()

        validator = PathValidator([str(base_dir)])

        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate(str(file_path))

    def test_empty_path_fails(self):
        """Empty path string is rejected."""
        validator = PathValidator(["/tmp"])

        with pytest.raises(PathValidationError, match="Empty path string"):
            validator.validate("")


class TestMultipleBaseDirectories:
    """Test validation with multiple whitelisted base directories."""

    def test_path_valid_if_in_any_base_directory(self, tmp_path):
        """Path is allowed if it's inside ANY of the base directories."""
        base1 = tmp_path / "base1"
        base1.mkdir()
        base2 = tmp_path / "base2"
        base2.mkdir()
        file1 = base1 / "file.txt"
        file1.touch()
        file2 = base2 / "file.txt"
        file2.touch()

        validator = PathValidator([str(base1), str(base2)])

        # Both files should pass
        result1 = validator.validate(str(file1))
        result2 = validator.validate(str(file2))

        assert result1.is_absolute()
        assert result2.is_absolute()

    def test_path_outside_all_base_directories_fails(self, tmp_path):
        """Path outside all base directories is rejected."""
        base1 = tmp_path / "base1"
        base1.mkdir()
        base2 = tmp_path / "base2"
        base2.mkdir()
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()
        file_path = forbidden / "file.txt"
        file_path.touch()

        validator = PathValidator([str(base1), str(base2)])

        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate(str(file_path))


class TestEmptyBaseDirectories:
    """Test behavior when no base directories are configured."""

    def test_empty_base_directories_allows_all_paths(self, tmp_path):
        """Empty base directories list allows all paths."""
        file_path = tmp_path / "anywhere" / "file.txt"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        validator = PathValidator([])
        result = validator.validate(str(file_path))

        assert result.is_absolute()

    def test_none_base_directories_allows_all_paths(self, tmp_path):
        """None base directories allows all paths."""
        file_path = tmp_path / "anywhere" / "file.txt"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        validator = PathValidator(None)
        result = validator.validate(str(file_path))

        assert result.is_absolute()


class TestRelativePathResolution:
    """Test handling of relative paths."""

    def test_relative_path_resolved_to_absolute(self, tmp_path, monkeypatch):
        """Relative paths are resolved to absolute."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # Change to base directory
        monkeypatch.chdir(base_dir)

        validator = PathValidator([str(base_dir)])
        result = validator.validate("file.txt")

        assert result.is_absolute()
        assert result == file_path.resolve()

    def test_relative_path_with_parent_refs(self, tmp_path, monkeypatch):
        """Relative paths with .. are resolved correctly."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        subdir = base_dir / "subdir"
        subdir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # Change to subdirectory
        monkeypatch.chdir(subdir)

        validator = PathValidator([str(base_dir)])
        # ../file.txt should resolve to allowed/file.txt
        result = validator.validate("../file.txt")

        assert result.is_absolute()
        assert result == file_path.resolve()


class TestSymlinkHandling:
    """Test symlink resolution before validation."""

    def test_symlink_inside_base_to_inside_passes(self, tmp_path):
        """Symlink inside base directory pointing to another location inside passes."""
        if sys.platform == "win32":
            pytest.skip("Symlink tests require administrator privileges on Windows")

        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        target = base_dir / "target.txt"
        target.touch()
        link = base_dir / "link.txt"
        link.symlink_to(target)

        validator = PathValidator([str(base_dir)])
        result = validator.validate(str(link))

        # Should resolve to the target
        assert result == target.resolve()

    def test_symlink_inside_base_to_outside_fails(self, tmp_path):
        """Symlink inside base directory pointing outside is rejected."""
        if sys.platform == "win32":
            pytest.skip("Symlink tests require administrator privileges on Windows")

        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()
        target = forbidden_dir / "target.txt"
        target.touch()
        link = base_dir / "link.txt"
        link.symlink_to(target)

        validator = PathValidator([str(base_dir)])

        # The link is inside base_dir, but it points outside
        # After resolution, the REAL location is outside
        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate(str(link))

    def test_symlink_chain_resolved_correctly(self, tmp_path):
        """Chain of symlinks is fully resolved before validation."""
        if sys.platform == "win32":
            pytest.skip("Symlink tests require administrator privileges on Windows")

        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        target = base_dir / "target.txt"
        target.touch()
        link1 = base_dir / "link1.txt"
        link1.symlink_to(target)
        link2 = base_dir / "link2.txt"
        link2.symlink_to(link1)

        validator = PathValidator([str(base_dir)])
        result = validator.validate(str(link2))

        # Should resolve through the chain to the target
        assert result == target.resolve()


class TestTraversalRejection:
    """Test rejection of directory traversal attempts."""

    def test_traversal_with_dotdot_outside_base_fails(self, tmp_path):
        """Path with .. that escapes base directory is rejected."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()

        validator = PathValidator([str(base_dir)])

        # Try to escape using ../forbidden
        escape_path = str(base_dir / ".." / "forbidden")

        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate(escape_path)

    def test_traversal_within_base_passes(self, tmp_path):
        """Path with .. that stays within base directory is allowed."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        subdir = base_dir / "subdir"
        subdir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        validator = PathValidator([str(base_dir)])

        # subdir/../file.txt should resolve to allowed/file.txt
        path_with_dotdot = str(subdir / ".." / "file.txt")
        result = validator.validate(path_with_dotdot)

        assert result == file_path.resolve()


class TestCrossPlatformNormalization:
    """Test cross-platform path normalization."""

    def test_case_sensitivity_matches_os(self, tmp_path):
        """Case sensitivity in path matching follows OS behavior."""
        base_dir = tmp_path / "Allowed"
        base_dir.mkdir()
        file_path = base_dir / "File.txt"
        file_path.touch()

        validator = PathValidator([str(base_dir)])

        if sys.platform == "win32":
            # Windows is case-insensitive
            # Should accept lowercase variant
            result = validator.validate(str(file_path).lower())
            assert result.is_absolute()
        else:
            # Unix is case-sensitive
            # Exact case should work
            result = validator.validate(str(file_path))
            assert result.is_absolute()

    def test_separator_normalization(self, tmp_path):
        """Path separators are normalized to OS-native format."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        file_path = base_dir / "subdir" / "file.txt"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        validator = PathValidator([str(base_dir)])

        # Create path with forward slashes (Unix-style)
        unix_style = str(base_dir).replace(os.sep, '/') + '/subdir/file.txt'
        result = validator.validate(unix_style)

        assert result.is_absolute()
        assert result == file_path.resolve()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows UNC path test")
    def test_windows_unc_path_handling(self):
        """Windows UNC paths are handled correctly."""
        # Note: This test requires actual network share access, so we just
        # verify the validator can handle UNC path format without error
        unc_base = r"\\localhost\share"
        validator = PathValidator([unc_base])

        # Verify initialization doesn't crash on UNC paths
        assert validator.base_directories == [unc_base]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_base_directory_with_trailing_separator(self, tmp_path):
        """Base directory with trailing separator works correctly."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # Add trailing separator
        base_with_sep = str(base_dir) + os.sep

        validator = PathValidator([base_with_sep])
        result = validator.validate(str(file_path))

        assert result.is_absolute()

    def test_deeply_nested_path(self, tmp_path):
        """Deeply nested paths are validated correctly."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()

        # Create deeply nested structure
        deep_path = base_dir / "a" / "b" / "c" / "d" / "e" / "file.txt"
        deep_path.parent.mkdir(parents=True)
        deep_path.touch()

        validator = PathValidator([str(base_dir)])
        result = validator.validate(str(deep_path))

        assert result == deep_path.resolve()

    def test_base_directory_properties(self, tmp_path):
        """Validator exposes base directory properties correctly."""
        base1 = tmp_path / "base1"
        base1.mkdir()
        base2 = tmp_path / "base2"
        base2.mkdir()

        validator = PathValidator([str(base1), str(base2)])

        # Original paths
        assert validator.base_directories == [str(base1), str(base2)]

        # Resolved paths (should be normalized)
        resolved = validator.resolved_base_directories
        assert len(resolved) == 2
        assert all(os.path.isabs(path) for path in resolved)

    def test_tilde_expansion(self, tmp_path):
        """Tilde (~) in paths is expanded to home directory."""
        # Create a validator with a temp base directory
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()

        validator = PathValidator([str(base_dir)])

        # Path with ~ should be expanded (though it will likely fail validation
        # unless home is under base_dir - we just test it doesn't crash)
        try:
            validator.validate("~/some/path")
        except PathValidationError:
            # Expected if home is not under base_dir
            pass
