"""Tests for BackgroundTaskRegistry."""

import sys

import anyio
import pytest

from async_crud_mcp.core.background_tasks import BackgroundTask, BackgroundTaskRegistry


class TestBackgroundTask:
    """Test BackgroundTask dataclass."""

    def test_initial_state(self):
        task = BackgroundTask(task_id="abc123", command="echo hello")
        assert task.task_id == "abc123"
        assert task.command == "echo hello"
        assert not task.is_complete
        assert task.exit_code is None
        assert task.duration_ms is None
        assert task.stdout == ""
        assert task.stderr == ""

    def test_complete_state(self):
        task = BackgroundTask(task_id="abc", command="test")
        task.exit_code = 0
        task.completed_at = task.started_at + 1.5
        assert task.is_complete
        assert task.duration_ms == 1500

    def test_stdout_stderr_decode(self):
        task = BackgroundTask(task_id="abc", command="test")
        task.stdout_buffer.extend(b"hello world")
        task.stderr_buffer.extend(b"error msg")
        assert task.stdout == "hello world"
        assert task.stderr == "error msg"


class TestBackgroundTaskRegistry:
    """Test BackgroundTaskRegistry management."""

    def test_create_task(self):
        registry = BackgroundTaskRegistry()
        task = registry.create_task("echo hello")
        assert task.task_id
        assert len(task.task_id) == 12
        assert task.command == "echo hello"

    def test_get_task(self):
        registry = BackgroundTaskRegistry()
        task = registry.create_task("echo hello")
        retrieved = registry.get(task.task_id)
        assert retrieved is task

    def test_get_nonexistent(self):
        registry = BackgroundTaskRegistry()
        assert registry.get("nonexistent") is None

    def test_remove_task(self):
        registry = BackgroundTaskRegistry()
        task = registry.create_task("echo hello")
        registry.remove(task.task_id)
        assert registry.get(task.task_id) is None

    def test_remove_nonexistent(self):
        """Remove of non-existent task should not raise."""
        registry = BackgroundTaskRegistry()
        registry.remove("nonexistent")

    def test_list_active(self):
        registry = BackgroundTaskRegistry()
        t1 = registry.create_task("cmd1")
        t2 = registry.create_task("cmd2")
        assert len(registry.list_active()) == 2

        t1.exit_code = 0
        active = registry.list_active()
        assert len(active) == 1
        assert active[0].task_id == t2.task_id


class TestBackgroundTaskRegistryAsync:
    """Test async operations."""

    @pytest.mark.asyncio
    async def test_wait_for_nonexistent(self):
        registry = BackgroundTaskRegistry()
        result = await registry.wait_for("nonexistent", timeout=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_already_complete(self):
        registry = BackgroundTaskRegistry()
        task = registry.create_task("echo done")
        task.exit_code = 0
        result = await registry.wait_for(task.task_id, timeout=1.0)
        assert result is task
        assert result.is_complete

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32" and not __import__("shutil").which("bash"),
                        reason="No bash available")
    async def test_run_background_captures_output(self):
        registry = BackgroundTaskRegistry()
        task = registry.create_task("echo hello")

        import shutil
        bash = shutil.which("bash")
        if not bash:
            pytest.skip("No bash available")

        exec_args = [bash, "-c", "echo hello"]
        await registry.run_background(task, exec_args)

        assert task.is_complete
        assert task.exit_code == 0
        assert "hello" in task.stdout

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        """Wait should return task even if not complete after timeout."""
        registry = BackgroundTaskRegistry()
        task = registry.create_task("long command")
        # Don't run the task, just wait for it
        result = await registry.wait_for(task.task_id, timeout=0.1)
        assert result is not None
        assert not result.is_complete
