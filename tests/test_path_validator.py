"""Tests for PathValidator security and cross-platform path handling."""

import os
import sys
from pathlib import Path

import pytest

from async_crud_mcp.config import PathRule
from async_crud_mcp.core.path_validator import AccessDeniedError, PathValidationError, PathValidator


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


class TestAccessRules:
    """Test access rule evaluation in validate_operation()."""

    def _make_rule(self, path, operations, action, priority=0):
        return PathRule(path=path, operations=operations, action=action, priority=priority)

    def test_allow_rule_permits_operation(self, tmp_path):
        """An allow rule for a matching path and operation permits the operation."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        output_dir = base_dir / "output"
        output_dir.mkdir()
        file_path = output_dir / "result.json"
        file_path.touch()

        rules = [self._make_rule(str(output_dir), ["write"], "allow", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="deny",
        )

        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

    def test_deny_rule_blocks_operation(self, tmp_path):
        """A deny rule for a matching path and operation blocks the operation."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        src_dir = base_dir / "src"
        src_dir.mkdir()
        file_path = src_dir / "main.py"
        file_path.touch()

        rules = [self._make_rule(str(src_dir), ["write"], "deny", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="allow",
        )

        with pytest.raises(AccessDeniedError, match="denied"):
            validator.validate_operation(str(file_path), "write")

    def test_default_policy_deny_blocks_unmatched_path(self, tmp_path):
        """Default deny policy blocks operations when no rule matches."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # No rules that match this path
        rules = [self._make_rule(str(base_dir / "other"), ["write"], "allow", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="deny",
        )

        with pytest.raises(AccessDeniedError, match="no matching access rule"):
            validator.validate_operation(str(file_path), "write")

    def test_default_policy_allow_permits_unmatched_path(self, tmp_path):
        """Default allow policy permits operations when no rule matches."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        rules = [self._make_rule(str(base_dir / "other"), ["write"], "deny", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="allow",
        )

        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

    def test_priority_ordering_higher_wins(self, tmp_path):
        """Higher priority rule wins over lower priority rule for same path."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        dir_a = base_dir / "src"
        dir_a.mkdir()
        file_path = dir_a / "file.py"
        file_path.touch()

        rules = [
            self._make_rule(str(dir_a), ["write"], "deny", priority=50),
            self._make_rule(str(dir_a), ["write"], "allow", priority=100),
        ]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="deny",
        )

        # Higher priority allow should win
        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

    def test_wildcard_operation_matches_any(self, tmp_path):
        """Wildcard '*' in operations matches any operation type."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        protected = base_dir / "protected"
        protected.mkdir()
        file_path = protected / "secret.txt"
        file_path.touch()

        rules = [self._make_rule(str(protected), ["*"], "deny", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="allow",
        )

        with pytest.raises(AccessDeniedError):
            validator.validate_operation(str(file_path), "write")
        with pytest.raises(AccessDeniedError):
            validator.validate_operation(str(file_path), "delete")
        with pytest.raises(AccessDeniedError):
            validator.validate_operation(str(file_path), "update")

    def test_operation_type_mismatch_skips_rule(self, tmp_path):
        """Rule with non-matching operation type is skipped."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # Deny delete but not write
        rules = [self._make_rule(str(base_dir), ["delete"], "deny", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="allow",
        )

        # Write should pass (rule only applies to delete)
        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

        # Delete should fail
        with pytest.raises(AccessDeniedError):
            validator.validate_operation(str(file_path), "delete")

    def test_no_rules_with_deny_default_blocks_all(self, tmp_path):
        """No access rules with deny default blocks all destructive operations."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        validator = PathValidator(
            [str(base_dir)],
            access_rules=[],
            default_destructive_policy="deny",
        )

        with pytest.raises(AccessDeniedError, match="no access rules configured"):
            validator.validate_operation(str(file_path), "write")

    def test_no_rules_with_allow_default_permits_all(self, tmp_path):
        """No access rules with allow default permits all destructive operations."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        validator = PathValidator(
            [str(base_dir)],
            access_rules=[],
            default_destructive_policy="allow",
        )

        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

    def test_backward_compat_no_access_config(self, tmp_path):
        """PathValidator without access config behaves identically to before."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        file_path = base_dir / "file.txt"
        file_path.touch()

        # Default constructor: no access_rules, default_destructive_policy="allow"
        validator = PathValidator([str(base_dir)])

        # validate_operation should behave like validate()
        result = validator.validate_operation(str(file_path), "write")
        assert result.is_absolute()

    def test_base_directory_still_enforced(self, tmp_path):
        """validate_operation still enforces base directory before access rules."""
        base_dir = tmp_path / "allowed"
        base_dir.mkdir()
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()
        file_path = forbidden_dir / "file.txt"
        file_path.touch()

        rules = [self._make_rule(str(forbidden_dir), ["write"], "allow", priority=100)]
        validator = PathValidator(
            [str(base_dir)],
            access_rules=rules,
            default_destructive_policy="allow",
        )

        # Should fail with PathValidationError (base dir), not AccessDeniedError
        with pytest.raises(PathValidationError, match="outside allowed base directories"):
            validator.validate_operation(str(file_path), "write")
