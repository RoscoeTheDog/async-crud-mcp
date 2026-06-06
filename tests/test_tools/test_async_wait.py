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
async def background_registry():
    registry = BackgroundTaskRegistry()
    try:
        yield registry
    finally:
        # Kill any still-running background subprocess and await its transport
        # close, so the test event loop has no orphaned IOCP read at teardown
        # (the Windows ProactorEventLoop GetQueuedCompletionStatus hang).
        await registry.shutdown()


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
        assert response.completed_tasks is not None
        assert len(response.completed_tasks) == 1
        assert response.completed_tasks[0].task_id == task.task_id
        assert response.completed_tasks[0].task_result.exit_code == 0

    @pytest.mark.asyncio
    async def test_wait_running_task_timeout(self, background_registry):
        """Waiting for a running task should return after timeout."""
        task = background_registry.create_task("long cmd")
        # Don't complete the task

        request = WaitRequest(task_id=task.task_id, seconds=0.1)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.task_status == "all_running"
        assert response.completed_tasks is None
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
        assert response.completed_tasks is not None
        assert fake_key not in response.completed_tasks[0].task_result.stdout
        assert "<<REDACTED:aws-access-key-id:1>>" in response.completed_tasks[0].task_result.stdout
        assert response.completed_tasks[0].stdout_redactions is not None
        assert response.completed_tasks[0].stdout_redactions[0].rule_name == "aws-access-key-id"

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
        assert response.completed_tasks is not None
        assert fake_key not in response.completed_tasks[0].task_result.stderr
        assert "<<REDACTED:aws-access-key-id:1>>" in response.completed_tasks[0].task_result.stderr
        assert response.completed_tasks[0].stderr_redactions is not None
        assert response.completed_tasks[0].stderr_redactions[0].rule_name == "aws-access-key-id"

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
        assert response.completed_tasks[0].task_result.stdout == "safe output\n"
        assert "REDACTED" not in response.completed_tasks[0].task_result.stdout
        assert response.completed_tasks[0].stdout_redactions is None
        assert response.completed_tasks[0].stderr_redactions is None

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
        assert fake_key in response.completed_tasks[0].task_result.stdout


class TestAsyncWaitMultiTask:
    """Test multi-task wait functionality."""

    @pytest.mark.asyncio
    async def test_multi_all_completed(self, background_registry):
        """Two completed tasks, pass both IDs. Both returned."""
        task1 = background_registry.create_task("echo one")
        task1.exit_code = 0
        task1.stdout_buffer.extend(b"one\n")
        task1.completed_at = task1.started_at + 0.1

        task2 = background_registry.create_task("echo two")
        task2.exit_code = 0
        task2.stdout_buffer.extend(b"two\n")
        task2.completed_at = task2.started_at + 0.2

        request = WaitRequest(task_id=[task1.task_id, task2.task_id], seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.task_status == "completed"
        assert response.completed_tasks is not None
        assert len(response.completed_tasks) == 2
        returned_ids = {r.task_id for r in response.completed_tasks}
        assert task1.task_id in returned_ids
        assert task2.task_id in returned_ids

    @pytest.mark.asyncio
    async def test_multi_some_completed(self, background_registry):
        """1 completed + 1 running. Only the completed one returned."""
        task_done = background_registry.create_task("echo done")
        task_done.exit_code = 0
        task_done.stdout_buffer.extend(b"done\n")
        task_done.completed_at = task_done.started_at + 0.1

        task_running = background_registry.create_task("long cmd")
        # Don't complete this one

        request = WaitRequest(task_id=[task_done.task_id, task_running.task_id], seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.task_status == "completed"
        assert response.completed_tasks is not None
        assert len(response.completed_tasks) == 1
        assert response.completed_tasks[0].task_id == task_done.task_id

    @pytest.mark.asyncio
    async def test_multi_none_completed_timeout(self, background_registry):
        """2 running, short timeout. all_running returned."""
        task1 = background_registry.create_task("long cmd 1")
        task2 = background_registry.create_task("long cmd 2")
        # Don't complete either

        request = WaitRequest(task_id=[task1.task_id, task2.task_id], seconds=0.1)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.task_status == "all_running"
        assert response.completed_tasks is None

    @pytest.mark.asyncio
    async def test_multi_not_found(self, background_registry):
        """List with nonexistent ID returns error."""
        task = background_registry.create_task("echo ok")
        task.exit_code = 0
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=[task.task_id, "nonexistent"], seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "error"
        assert response.error_code == ErrorCode.TASK_NOT_FOUND
        assert "nonexistent" in response.message

    @pytest.mark.asyncio
    async def test_multi_empty_list(self, background_registry):
        """Empty list falls through to sleep."""
        request = WaitRequest(task_id=[], seconds=0.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert "Slept" in response.reason

    @pytest.mark.asyncio
    async def test_multi_redaction(self, background_registry, content_scanner):
        """Completed task with sensitive data gets redactions in completed_tasks."""
        fake_key = "AKIAIOSFODNN7EXAMPLE"
        task = background_registry.create_task("echo secret")
        task.exit_code = 0
        task.stdout_buffer.extend(f"key={fake_key}\n".encode())
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=[task.task_id], seconds=1.0)
        response = await async_wait(request, background_registry, content_scanner=content_scanner)
        assert response.status == "ok"
        assert response.completed_tasks is not None
        assert len(response.completed_tasks) == 1
        assert fake_key not in response.completed_tasks[0].task_result.stdout
        assert response.completed_tasks[0].stdout_redactions is not None
        assert response.completed_tasks[0].stdout_redactions[0].rule_name == "aws-access-key-id"

    @pytest.mark.asyncio
    async def test_multi_duplicate_ids(self, background_registry):
        """Duplicate IDs are deduplicated, returns 1 result."""
        task = background_registry.create_task("echo dup")
        task.exit_code = 0
        task.stdout_buffer.extend(b"dup\n")
        task.completed_at = task.started_at + 0.1

        request = WaitRequest(task_id=[task.task_id, task.task_id], seconds=1.0)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert response.completed_tasks is not None
        assert len(response.completed_tasks) == 1
        assert response.completed_tasks[0].task_id == task.task_id
