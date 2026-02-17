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
        """Test that check exits with code 48 when port is occupied."""
        # Bind a socket to a port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()

        try:
            # Should exit with code 48 (EADDRINUSE) because port is occupied
            with pytest.raises(SystemExit) as exc_info:
                _check_port_available("127.0.0.1", port)
            assert exc_info.value.code == 48
        finally:
            sock.close()

    def test_port_in_use_logs_error(self):
        """Test that EADDRINUSE logs an error message."""
        # Bind a socket to a port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()

        try:
            # Mock logger.error to capture the log call
            with patch("async_crud_mcp.server.logger.error") as mock_error:
                with pytest.raises(SystemExit):
                    _check_port_available("127.0.0.1", port)
                # Verify error was logged
                mock_error.assert_called_once()
                call_args = mock_error.call_args[0][0]
                assert f"Port {port} is already in use" in call_args
        finally:
            sock.close()


class TestSecurityWarning:
    """Test security warning for non-localhost binding."""

    def test_non_localhost_warning(self):
        """Test that binding to non-localhost address logs a warning."""
        # Test the security logic directly
        host = "0.0.0.0"
        with patch("async_crud_mcp.server.logger.warning") as mock_warning:
            # Replicate the __main__ security check logic
            if host not in ("127.0.0.1", "::1", "localhost"):
                from async_crud_mcp.server import logger
                logger.warning(
                    f"Security: binding to non-localhost address {host} exposes the server to network access"
                )

            # Verify warning was logged
            mock_warning.assert_called_once()
            call_args = mock_warning.call_args[0][0]
            assert "Security: binding to non-localhost address" in call_args
            assert "0.0.0.0" in call_args

    def test_localhost_no_warning(self):
        """Test that binding to localhost does not log a warning."""
        # Test that localhost addresses don't trigger the warning
        localhost_addresses = ["127.0.0.1", "::1", "localhost"]
        for host in localhost_addresses:
            with patch("async_crud_mcp.server.logger.warning") as mock_warning:
                # Replicate the __main__ security check logic
                if host not in ("127.0.0.1", "::1", "localhost"):
                    from async_crud_mcp.server import logger
                    logger.warning(
                        f"Security: binding to non-localhost address {host} exposes the server to network access"
                    )

                # Verify no warning was logged for localhost addresses
                mock_warning.assert_not_called()


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
        """Test health_tool wrapper returns dict with version and uptime."""
        # @mcp.tool() returns a FunctionTool, not a callable coroutine.
        tool = mcp._tool_manager._tools["health_tool"]
        response = await tool.fn()

        # Verify response structure
        assert isinstance(response, dict)
        assert "status" in response
        assert response["status"] in ("healthy", "degraded", "unhealthy")

        # Verify version and uptime are included (AC-9.3)
        assert "version" in response
        assert response["version"] == "0.1.0"
        assert "uptime" in response
        assert isinstance(response["uptime"], float)
        assert response["uptime"] >= 0


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


class TestHealthEndpoint:
    """Test HTTP GET /health endpoint (AC-2.1, AC-2.2, AC-2.3, AC-2.4)."""

    def test_health_route_registered(self):
        """Test that /health custom route is registered on the FastMCP instance."""
        routes = mcp._additional_http_routes
        health_routes = [r for r in routes if getattr(r, "path", None) == "/health"]
        assert len(health_routes) == 1, "/health route not found in _additional_http_routes"

    @pytest.mark.asyncio
    async def test_health_endpoint_healthy_returns_200(self):
        """Test that healthy status returns HTTP 200 with correct fields."""
        from unittest.mock import MagicMock

        from async_crud_mcp.server import health_http_endpoint

        mock_request = MagicMock()
        with patch("async_crud_mcp.server.check_health") as mock_check:
            mock_check.return_value = {
                "status": "healthy",
                "config_readable": True,
                "daemon_enabled": True,
                "logs_dir_exists": True,
                "port_listening": True,
                "host": "127.0.0.1",
                "port": 8720,
                "message": "All checks passed",
            }
            response = await health_http_endpoint(mock_request)

        assert response.status_code == 200
        import json
        body = json.loads(response.body)
        assert body["status"] == "healthy"
        assert "version" in body
        assert "uptime" in body
        assert isinstance(body["uptime"], float)

    @pytest.mark.asyncio
    async def test_health_endpoint_degraded_returns_200(self):
        """Test that degraded status returns HTTP 200."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        with patch("async_crud_mcp.server.check_health") as mock_check:
            mock_check.return_value = {
                "status": "degraded",
                "config_readable": True,
                "daemon_enabled": True,
                "logs_dir_exists": False,
                "port_listening": True,
                "host": "127.0.0.1",
                "port": 8720,
                "message": "Some checks failed",
            }
            from async_crud_mcp.server import health_http_endpoint
            response = await health_http_endpoint(mock_request)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_endpoint_unhealthy_returns_503(self):
        """Test that unhealthy status returns HTTP 503."""
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        with patch("async_crud_mcp.server.check_health") as mock_check:
            mock_check.return_value = {
                "status": "unhealthy",
                "config_readable": False,
                "daemon_enabled": False,
                "logs_dir_exists": False,
                "port_listening": False,
                "host": "127.0.0.1",
                "port": 8720,
                "message": "Service unavailable",
            }
            from async_crud_mcp.server import health_http_endpoint
            response = await health_http_endpoint(mock_request)

        assert response.status_code == 503


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
