"""Tests for ShellValidator deny pattern matching."""

import pytest

from async_crud_mcp.config import ShellDenyPattern, _default_deny_patterns
from async_crud_mcp.core.shell_validator import ShellValidator


@pytest.fixture
def default_validator():
    """Validator with default deny patterns."""
    return ShellValidator(_default_deny_patterns())


@pytest.fixture
def custom_validator():
    """Validator with custom patterns."""
    patterns = [
        ShellDenyPattern(pattern=r"\bfoo\b", reason="foo is denied"),
        ShellDenyPattern(pattern=r"dangerous", reason="dangerous commands denied"),
    ]
    return ShellValidator(patterns)


class TestShellValidatorDenyPatterns:
    """Test deny pattern matching."""

    def test_cat_denied(self, default_validator):
        allowed, pattern, reason = default_validator.validate("cat /etc/passwd")
        assert not allowed
        assert "cat" in pattern
        assert "async_read" in reason.lower()

    def test_sed_denied(self, default_validator):
        allowed, pattern, reason = default_validator.validate("sed -i 's/old/new/g' file.txt")
        assert not allowed
        assert "sed" in pattern

    def test_rm_denied(self, default_validator):
        allowed, pattern, reason = default_validator.validate("rm -rf /tmp/stuff")
        assert not allowed
        assert "rm" in pattern

    def test_echo_redirect_denied(self, default_validator):
        allowed, pattern, reason = default_validator.validate("echo 'hello' > file.txt")
        assert not allowed

    def test_sudo_denied(self, default_validator):
        allowed, pattern, reason = default_validator.validate("sudo apt install foo")
        assert not allowed

    def test_git_allowed(self, default_validator):
        allowed, pattern, reason = default_validator.validate("git status")
        assert allowed
        assert pattern == ""

    def test_pytest_allowed(self, default_validator):
        allowed, pattern, reason = default_validator.validate("pytest tests/ -v")
        assert allowed

    def test_npm_allowed(self, default_validator):
        allowed, pattern, reason = default_validator.validate("npm install express")
        assert allowed

    def test_pip_allowed(self, default_validator):
        allowed, pattern, reason = default_validator.validate("pip install requests")
        assert allowed

    def test_python_c_denied(self, default_validator):
        """python -c is blocked to prevent inline code execution bypass."""
        allowed, pattern, reason = default_validator.validate("python -c 'print(1)'")
        assert not allowed

    def test_python_script_allowed(self, default_validator):
        """Running a python script file is allowed."""
        allowed, pattern, reason = default_validator.validate("python script.py")
        assert allowed

    def test_ls_allowed(self, default_validator):
        """ls is not in the deny list (read-only directory listing)."""
        allowed, _, _ = default_validator.validate("ls -la")
        assert allowed

    def test_grep_allowed(self, default_validator):
        """grep is allowed (read-only search)."""
        allowed, _, _ = default_validator.validate("grep -r 'pattern' .")
        assert allowed

    def test_echo_without_redirect_allowed(self, default_validator):
        """echo without > redirect should be allowed."""
        allowed, _, _ = default_validator.validate("echo hello world")
        assert allowed

    def test_mv_denied(self, default_validator):
        allowed, _, _ = default_validator.validate("mv old.txt new.txt")
        assert not allowed

    def test_cp_denied(self, default_validator):
        allowed, _, _ = default_validator.validate("cp src.txt dst.txt")
        assert not allowed

    def test_chmod_denied(self, default_validator):
        allowed, _, _ = default_validator.validate("chmod 755 script.sh")
        assert not allowed


class TestShellValidatorCustom:
    """Test custom patterns."""

    def test_custom_pattern_match(self, custom_validator):
        allowed, pattern, reason = custom_validator.validate("run foo now")
        assert not allowed
        assert reason == "foo is denied"

    def test_custom_pattern_no_match(self, custom_validator):
        allowed, _, _ = custom_validator.validate("safe command")
        assert allowed

    def test_pattern_count(self, custom_validator):
        assert custom_validator.pattern_count == 2


class TestShellValidatorReload:
    """Test pattern reload."""

    def test_reload_replaces_patterns(self):
        original = [ShellDenyPattern(pattern=r"\bold\b", reason="old denied")]
        validator = ShellValidator(original)
        allowed, _, _ = validator.validate("old command")
        assert not allowed

        new = [ShellDenyPattern(pattern=r"\bnew\b", reason="new denied")]
        validator.reload(new)

        # Old pattern should no longer match
        allowed, _, _ = validator.validate("old command")
        assert allowed

        # New pattern should match
        allowed, _, _ = validator.validate("new command")
        assert not allowed

    def test_reload_invalid_pattern_skipped(self):
        """Invalid regex patterns should be silently skipped."""
        patterns = [
            ShellDenyPattern(pattern=r"[invalid", reason="bad regex"),
            ShellDenyPattern(pattern=r"\bgood\b", reason="good pattern"),
        ]
        validator = ShellValidator(patterns)
        assert validator.pattern_count == 1

    def test_empty_patterns(self):
        validator = ShellValidator([])
        allowed, _, _ = validator.validate("anything goes")
        assert allowed
        assert validator.pattern_count == 0
