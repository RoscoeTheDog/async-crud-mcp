"""Tests for async_wait tool."""

import shutil

import pytest

from async_crud_mcp.config import ContentRule
from async_crud_mcp.core.background_tasks import BackgroundTask, BackgroundTaskRegistry
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.models.requests import WaitRequest
from async_crud_mcp.models.responses import ErrorCode
from async_crud_mcp.tools.async_wait import async_wait


@pytest.fixture
def background_registry():
    return BackgroundTaskRegistry()


class TestAsyncWaitSleep:
    """Test simple sleep functionality."""

    @pytest.mark.asyncio
    async def test_sleep_zero(self, background_registry):
        request = WaitRequest(seconds=0.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.waited_seconds >= 0.0
        assert "Slept" in response.reason

    @pytest.mark.asyncio
    async def test_sleep_short(self, background_registry):
        request = WaitRequest(seconds=0.1)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.waited_seconds >= 0.05  # Allow some tolerance


class TestAsyncWaitTask:
    """Test task waiting functionality."""

    @pytest.mark.asyncio
    async def test_wait_nonexistent_task(self, background_registry):
        request = WaitRequest(task_id="nonexistent", seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "error"
        assert response.error_code == ErrorCode.TASK_NOT_FOUND

    @pytest.mark.asyncio
    async def test_wait_completed_task(self, background_registry):
        task = background_registry.create_task("echo done")
        task.exit_code = 0
        task.stdout_buffer.extend(b"done\n")
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=task.task_id, seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.waited_seconds == 0.0
        assert response.task_result is not None
        assert response.task_result.exit_code == 0

    @pytest.mark.asyncio
    async def test_wait_running_task_timeout(self, background_registry):
        """Waiting for a running task should return after timeout."""
        task = background_registry.create_task("long cmd")
        # Don't complete the task

        request = WaitRequest(task_id=task.task_id, seconds=0.1)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert "still running" in response.reason


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


class TestAsyncWaitRedaction:
    """Test content scanner redaction of background task output."""

    @pytest.mark.asyncio
    async def test_completed_task_stdout_redacted(self, background_registry, content_scanner):
        """Sensitive data in completed task stdout should be redacted."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        task = background_registry.create_task("echo secret")
        task.exit_code = 0
        task.stdout_buffer.extend(f"key={fake_key}\n".encode())
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=task.task_id, seconds=1.0)
        response = await async_wait(request, background_registry, content_scanner=content_scanner)
        assert response.status == "ok"
        assert response.task_result is not None
        assert fake_key not in response.task_result.stdout
        assert "<<REDACTED:aws-access-key-id:1>>" in response.task_result.stdout
        assert response.stdout_redactions is not None
        assert response.stdout_redactions[0].rule_name == "aws-access-key-id"

    @pytest.mark.asyncio
    async def test_completed_task_stderr_redacted(self, background_registry, content_scanner):
        """Sensitive data in completed task stderr should be redacted."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        task = background_registry.create_task("echo secret >&2")
        task.exit_code = 1
        task.stderr_buffer.extend(f"error: {fake_key}\n".encode())
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=task.task_id, seconds=1.0)
        response = await async_wait(request, background_registry, content_scanner=content_scanner)
        assert response.status == "ok"
        assert response.task_result is not None
        assert fake_key not in response.task_result.stderr
        assert "<<REDACTED:aws-access-key-id:1>>" in response.task_result.stderr
        assert response.stderr_redactions is not None
        assert response.stderr_redactions[0].rule_name == "aws-access-key-id"

    @pytest.mark.asyncio
    async def test_clean_output_unchanged(self, background_registry, content_scanner):
        """Non-sensitive task output should pass through unchanged."""
        task = background_registry.create_task("echo safe")
        task.exit_code = 0
        task.stdout_buffer.extend(b"safe output\n")
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=task.task_id, seconds=1.0)
        response = await async_wait(request, background_registry, content_scanner=content_scanner)
        assert response.status == "ok"
        assert response.task_result.stdout == "safe output\n"
        assert "REDACTED" not in response.task_result.stdout
        assert response.stdout_redactions is None
        assert response.stderr_redactions is None

    @pytest.mark.asyncio
    async def test_no_scanner_passes_through(self, background_registry):
        """Without content_scanner, sensitive data passes through."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        task = background_registry.create_task("echo secret")
        task.exit_code = 0
        task.stdout_buffer.extend(f"key={fake_key}\n".encode())
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=task.task_id, seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert fake_key in response.task_result.stdout
