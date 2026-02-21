"""Tests for ShellProvider cross-platform shell detection."""

import os
import sys
from unittest.mock import patch

import pytest

from async_crud_mcp.core.shell_provider import ShellNotFoundError, ShellProvider


class TestShellProvider:
    """Test ShellProvider shell detection and build_exec_args."""

    def test_shell_path_is_cached(self):
        """Shell path should be detected once and cached."""
        provider = ShellProvider()
        path1 = provider.shell_path
        path2 = provider.shell_path
        assert path1 == path2

    def test_shell_path_exists(self):
        """Detected shell should be a real file."""
        provider = ShellProvider()
        assert os.path.isfile(provider.shell_path)

    def test_build_exec_args(self):
        """build_exec_args should return [shell, '-c', command]."""
        provider = ShellProvider()
        args = provider.build_exec_args("echo hello")
        assert len(args) == 3
        assert args[1] == "-c"
        assert args[2] == "echo hello"
        assert os.path.isfile(args[0])

    def test_build_exec_args_preserves_command(self):
        """Command string should be passed through unchanged."""
        provider = ShellProvider()
        cmd = "git status && echo done"
        args = provider.build_exec_args(cmd)
        assert args[2] == cmd


class TestShellProviderPosix:
    """Tests specific to POSIX shell detection."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
    def test_finds_bash_on_posix(self):
        provider = ShellProvider()
        shell = provider.shell_path
        assert "bash" in shell or "sh" in shell

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
    def test_respects_shell_env(self):
        """Should prefer SHELL env var if it's bash/zsh."""
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            provider = ShellProvider()
            if os.path.isfile("/bin/bash"):
                assert provider.shell_path == "/bin/bash"


class TestShellProviderWindows:
    """Tests specific to Windows shell detection."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_finds_bash_on_windows(self):
        provider = ShellProvider()
        shell = provider.shell_path
        assert "bash" in shell.lower()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_respects_env_var(self):
        """Should prefer CLAUDE_CODE_GIT_BASH_PATH if set and valid."""
        # Find actual bash first
        provider = ShellProvider()
        real_bash = provider.shell_path

        with patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": real_bash}):
            fresh = ShellProvider()
            assert fresh.shell_path == real_bash

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_invalid_env_var_skipped(self):
        """Should skip CLAUDE_CODE_GIT_BASH_PATH if file doesn't exist."""
        with patch.dict(os.environ, {"CLAUDE_CODE_GIT_BASH_PATH": r"C:\nonexistent\bash.exe"}):
            provider = ShellProvider()
            # Should still find bash through other means
            assert os.path.isfile(provider.shell_path)


class TestShellProviderNotFound:
    """Test error handling when no shell is found."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
    def test_raises_on_no_bash_windows(self):
        """Should raise ShellNotFoundError with guidance."""
        with patch("async_crud_mcp.core.shell_provider.shutil.which", return_value=None), \
             patch("async_crud_mcp.core.shell_provider.os.path.isfile", return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            provider = ShellProvider()
            with pytest.raises(ShellNotFoundError, match="Git Bash"):
                _ = provider.shell_path

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific")
    def test_raises_on_no_shell_posix(self):
        """Should raise ShellNotFoundError when nothing is found."""
        with patch("shutil.which", return_value=None), \
             patch.dict(os.environ, {}, clear=True), \
             patch("os.path.isfile", return_value=False):
            provider = ShellProvider()
            with pytest.raises(ShellNotFoundError, match="No suitable shell"):
                _ = provider.shell_path
