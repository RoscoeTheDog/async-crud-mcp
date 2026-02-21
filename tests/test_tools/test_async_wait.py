"""Tests for async_wait tool."""

import shutil

import pytest

from async_crud_mcp.core.background_tasks import BackgroundTask, BackgroundTaskRegistry
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
        assert response.task_result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_wait_running_task_timeout(self, background_registry):
        """Waiting for a running task should return after timeout."""
        task = background_registry.create_task("long cmd")
        # Don't complete the task

        request = WaitRequest(task_id=task.task_id, seconds=0.1)
        response = await async_wait(request, background_registry)
        assert response.status == "ok"
        assert "still running" in response.reason
