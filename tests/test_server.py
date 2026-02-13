"""Tests for FastMCP server module."""

import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from async_crud_mcp.server import _check_port_available, mcp


class TestPortPreflightCheck:
    """Test port availability checking."""

    def test_port_available_success(self):
        """Test that check passes when port is free."""
        # Find a free port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
        sock.close()

        # Should not raise
        _check_port_available("127.0.0.1", port)

    def test_port_already_in_use(self):
        """Test that check raises RuntimeError when port is occupied."""
        # Bind a socket to a port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()

        try:
            # Should raise because port is occupied
            with pytest.raises(RuntimeError, match=f"Port {port} is already in use"):
                _check_port_available("127.0.0.1", port)
        finally:
            sock.close()


class TestFastMCPServer:
    """Test FastMCP server instance and tool registration."""

    def test_server_instance_created(self):
        """Test that FastMCP server instance is created with correct name."""
        assert mcp is not None
        assert mcp.name == "async-crud-mcp"

    def test_tools_registered(self):
        """Test that all 11 CRUD tools + health tool are registered."""
        # Get registered tool names from the FastMCP instance
        # FastMCP stores tools in _tool_manager._tools dict
        tool_names = list(mcp._tool_manager._tools.keys())

        expected_tools = [
            "async_read_tool",
            "async_write_tool",
            "async_update_tool",
            "async_delete_tool",
            "async_rename_tool",
            "async_append_tool",
            "async_list_tool",
            "async_status_tool",
            "async_batch_read_tool",
            "async_batch_write_tool",
            "async_batch_update_tool",
            "health_tool",
        ]

        for expected_tool in expected_tools:
            assert expected_tool in tool_names, f"Tool {expected_tool} not registered"

    def test_tool_count(self):
        """Test that exactly 12 tools are registered (11 CRUD + 1 health)."""
        tool_count = len(mcp._tool_manager._tools)
        assert tool_count == 12, f"Expected 12 tools, found {tool_count}"


class TestToolWrappers:
    """Test individual tool wrappers."""

    @pytest.fixture
    def temp_base_dir(self):
        """Create a temporary base directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_async_read_tool_wrapper(self, temp_base_dir):
        """Test async_read_tool wrapper with minimal parameters."""
        # Create a test file
        test_file = temp_base_dir / "test.txt"
        test_file.write_text("test content\n")

        # Mock the settings to include temp_base_dir
        with patch("async_crud_mcp.server.settings") as mock_settings:
            mock_settings.crud.base_directories = [str(temp_base_dir)]

            # @mcp.tool() returns a FunctionTool, not a callable coroutine.
            # Access the underlying function via _tool_manager._tools.
            tool = mcp._tool_manager._tools["async_read_tool"]
            response = await tool.fn(
                path=str(test_file),
                offset=0,
                limit=None,
                encoding="utf-8",
            )

            # Verify response structure
            assert isinstance(response, dict)
            assert "content" in response or "error_code" in response

    @pytest.mark.asyncio
    async def test_health_tool_wrapper(self):
        """Test health_tool wrapper returns dict."""
        # @mcp.tool() returns a FunctionTool, not a callable coroutine.
        tool = mcp._tool_manager._tools["health_tool"]
        response = await tool.fn()

        # Verify response structure
        assert isinstance(response, dict)
        assert "status" in response
        assert response["status"] in ("healthy", "degraded", "unhealthy")


class TestServerConfiguration:
    """Test server configuration from settings."""

    def test_default_port_configuration(self):
        """Test that settings.daemon.port defaults to 8720."""
        from async_crud_mcp.server import settings

        assert settings.daemon.port is not None
        assert settings.daemon.port == 8720

    def test_default_host_configuration(self):
        """Test that settings.daemon.host defaults to 127.0.0.1."""
        from async_crud_mcp.server import settings

        assert settings.daemon.host == "127.0.0.1"

    def test_default_transport_configuration(self):
        """Test that settings.daemon.transport defaults to sse."""
        from async_crud_mcp.server import settings

        assert settings.daemon.transport == "sse"


class TestSharedDependencies:
    """Test shared dependency initialization."""

    def test_path_validator_initialized(self):
        """Test that PathValidator is initialized at module level."""
        from async_crud_mcp.server import path_validator

        assert path_validator is not None
        assert hasattr(path_validator, "validate")

    def test_lock_manager_initialized(self):
        """Test that LockManager is initialized at module level."""
        from async_crud_mcp.server import lock_manager

        assert lock_manager is not None
        assert hasattr(lock_manager, "acquire_read")
        assert hasattr(lock_manager, "acquire_write")

    def test_hash_registry_initialized(self):
        """Test that HashRegistry is initialized at module level."""
        from async_crud_mcp.server import hash_registry

        assert hash_registry is not None
        assert hasattr(hash_registry, "get")
        assert hasattr(hash_registry, "update")

    def test_server_start_time_initialized(self):
        """Test that server_start_time is a float timestamp."""
        from async_crud_mcp.server import server_start_time

        assert isinstance(server_start_time, float)
        assert server_start_time > 0
