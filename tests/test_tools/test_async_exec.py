"""Tests for async_exec tool."""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.config import ContentRule, ShellConfig, ShellDenyPattern, _default_deny_patterns
from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.core.shell_provider import ShellProvider
from async_crud_mcp.core.shell_validator import ShellValidator
from async_crud_mcp.models.requests import ExecRequest
from async_crud_mcp.models.responses import ErrorCode
from async_crud_mcp.tools.async_exec import async_exec


@pytest.fixture
def shell_config():
    return ShellConfig()


@pytest.fixture
def shell_provider():
    return ShellProvider()


@pytest.fixture
def shell_validator():
    return ShellValidator(_default_deny_patterns())


@pytest.fixture
def background_registry():
    return BackgroundTaskRegistry()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _has_bash():
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _has_bash(), reason="No bash available")
class TestAsyncExecDeny:
    """Test command denial."""

    @pytest.mark.asyncio
    async def test_cat_denied(self, shell_config, shell_provider, shell_validator, background_registry):
        request = ExecRequest(command="cat /etc/passwd")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry
        )
        assert response.status == "denied"
        assert "cat" in response.matched_pattern

    @pytest.mark.asyncio
    async def test_rm_denied(self, shell_config, shell_provider, shell_validator, background_registry):
        request = ExecRequest(command="rm -rf /tmp/stuff")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry
        )
        assert response.status == "denied"

    @pytest.mark.asyncio
    async def test_sudo_denied(self, shell_config, shell_provider, shell_validator, background_registry):
        request = ExecRequest(command="sudo ls")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry
        )
        assert response.status == "denied"


@pytest.mark.skipif(not _has_bash(), reason="No bash available")
class TestAsyncExecAllow:
    """Test allowed commands."""

    @pytest.mark.asyncio
    async def test_echo_no_redirect(self, shell_config, shell_provider, shell_validator, background_registry, temp_dir):
        request = ExecRequest(command="echo hello world")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "ok"
        assert "hello world" in response.stdout
        assert response.exit_code == 0

    @pytest.mark.asyncio
    async def test_git_status(self, shell_config, shell_provider, shell_validator, background_registry, temp_dir):
        """git status should be allowed (may fail if not a repo, but not denied)."""
        request = ExecRequest(command="git --version")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "ok"
        assert response.exit_code == 0

    @pytest.mark.asyncio
    async def test_exit_code_nonzero(self, shell_config, shell_provider, shell_validator, background_registry, temp_dir):
        request = ExecRequest(command="exit 42")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "ok"
        assert response.exit_code == 42


@pytest.mark.skipif(not _has_bash(), reason="No bash available")
class TestAsyncExecConfig:
    """Test configuration enforcement."""

    @pytest.mark.asyncio
    async def test_shell_disabled(self, shell_provider, shell_validator, background_registry):
        config = ShellConfig(enabled=False)
        request = ExecRequest(command="echo hello")
        response = await async_exec(
            request, config, shell_provider, shell_validator, background_registry
        )
        assert response.status == "error"
        assert response.error_code == ErrorCode.SHELL_DISABLED

    @pytest.mark.asyncio
    async def test_command_too_long(self, shell_provider, shell_validator, background_registry):
        config = ShellConfig(max_command_length=10)
        request = ExecRequest(command="a" * 20)
        response = await async_exec(
            request, config, shell_provider, shell_validator, background_registry
        )
        assert response.status == "error"
        assert response.error_code == ErrorCode.COMMAND_DENIED

    @pytest.mark.asyncio
    async def test_timeout(self, shell_config, shell_provider, shell_validator, background_registry, temp_dir):
        request = ExecRequest(command="sleep 10", timeout=0.5)
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "error"
        assert response.error_code == ErrorCode.COMMAND_TIMEOUT

    @pytest.mark.asyncio
    async def test_env_strip(self, shell_provider, shell_validator, background_registry, temp_dir):
        """Sensitive env vars should be stripped."""
        config = ShellConfig(env_strip=["MY_SECRET"])
        request = ExecRequest(command="echo done", env={"SAFE_VAR": "yes"})
        response = await async_exec(
            request, config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "ok"


@pytest.mark.skipif(not _has_bash(), reason="No bash available")
class TestAsyncExecBackground:
    """Test background execution."""

    @pytest.mark.asyncio
    async def test_background_returns_task_id(self, shell_config, shell_provider, shell_validator, background_registry, temp_dir):
        request = ExecRequest(command="echo background", background=True)
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "background"
        assert response.task_id
        assert response.command == "echo background"


@pytest.fixture
def content_scanner():
    """Scanner with AWS key detection rule."""
    rules = [
        ContentRule(
            name="aws-access-key-id",
            pattern=r"AKIA[0-9A-Z]{16}",
            action="deny",
            priority=100,
        ),
    ]
    return ContentScanner(rules=rules, enabled=True)


@pytest.mark.skipif(not _has_bash(), reason="No bash available")
class TestAsyncExecRedaction:
    """Test content scanner redaction of exec output."""

    @pytest.mark.asyncio
    async def test_stdout_redacted(
        self, shell_config, shell_provider, shell_validator, background_registry, temp_dir, content_scanner
    ):
        """Sensitive data in stdout should be redacted."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        request = ExecRequest(command=f"echo {fake_key}")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
            content_scanner=content_scanner,
        )
        assert response.status == "ok"
        assert fake_key not in response.stdout
        assert "<<REDACTED:aws-access-key-id:1>>" in response.stdout

    @pytest.mark.asyncio
    async def test_clean_stdout_unchanged(
        self, shell_config, shell_provider, shell_validator, background_registry, temp_dir, content_scanner
    ):
        """Non-sensitive output should pass through unchanged."""
        request = ExecRequest(command="echo hello world")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
            content_scanner=content_scanner,
        )
        assert response.status == "ok"
        assert "hello world" in response.stdout
        assert "REDACTED" not in response.stdout

    @pytest.mark.asyncio
    async def test_no_scanner_passes_through(
        self, shell_config, shell_provider, shell_validator, background_registry, temp_dir
    ):
        """Without content_scanner, sensitive data passes through."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        request = ExecRequest(command=f"echo {fake_key}")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
        )
        assert response.status == "ok"
        assert fake_key in response.stdout

    @pytest.mark.asyncio
    async def test_stderr_redacted(
        self, shell_config, shell_provider, shell_validator, background_registry, temp_dir, content_scanner
    ):
        """Sensitive data in stderr should be redacted."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        request = ExecRequest(command=f"echo {fake_key} >&2")
        response = await async_exec(
            request, shell_config, shell_provider, shell_validator, background_registry,
            project_root=temp_dir,
            content_scanner=content_scanner,
        )
        assert response.status == "ok"
        assert fake_key not in response.stderr
        assert "<<REDACTED:aws-access-key-id:1>>" in response.stderr
