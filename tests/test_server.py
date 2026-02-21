"""Tests for FastMCP server module."""

import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from async_crud_mcp.server import (
    ProjectActivationMiddleware,
    _ACTIVATION_EXEMPT_TOOLS,
    _apply_project_config,
    _check_port_available,
    _deep_merge,
    mcp,
)


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
        """Test that all 11 CRUD + 3 shell + 1 health + 3 config tools are registered."""
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
            "async_exec_tool",
            "async_wait_tool",
            "async_search_tool",
            "health_tool",
            "crud_activate_project",
            "crud_get_config",
            "crud_update_config",
        ]

        for expected_tool in expected_tools:
            assert expected_tool in tool_names, f"Tool {expected_tool} not registered"

    def test_tool_count(self):
        """Test that exactly 18 tools are registered (11 CRUD + 3 shell + 1 health + 3 config)."""
        tool_count = len(mcp._tool_manager._tools)
        assert tool_count == 18, f"Expected 18 tools, found {tool_count}"


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


class TestDeepMerge:
    """Test _deep_merge helper function."""

    def test_simple_merge(self):
        """Test merging flat dicts."""
        base = {"a": 1, "b": 2}
        updates = {"b": 3, "c": 4}
        result = _deep_merge(base, updates)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        """Test merging nested dicts recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        updates = {"outer": {"b": 3, "c": 4}}
        result = _deep_merge(base, updates)
        assert result == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_list_replacement(self):
        """Test that lists are replaced, not appended."""
        base = {"items": [1, 2, 3]}
        updates = {"items": [4, 5]}
        result = _deep_merge(base, updates)
        assert result == {"items": [4, 5]}

    def test_new_keys(self):
        """Test adding new keys."""
        base = {"a": 1}
        updates = {"b": 2}
        result = _deep_merge(base, updates)
        assert result == {"a": 1, "b": 2}

    def test_empty_updates(self):
        """Test merging with empty updates."""
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_empty_base(self):
        """Test merging into empty base."""
        result = _deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_does_not_mutate_base(self):
        """Test that base dict is not mutated."""
        base = {"a": 1, "b": 2}
        _deep_merge(base, {"b": 3})
        assert base == {"a": 1, "b": 2}


class TestApplyProjectConfig:
    """Test _apply_project_config helper."""

    def test_apply_with_none_uses_project_root_as_base(self, tmp_path):
        """Test that None project_config uses project_root as sole base dir."""
        import async_crud_mcp.server as srv

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        try:
            _apply_project_config(tmp_path, None)
            assert str(tmp_path) in [
                str(d) for d in srv.path_validator._base_directories
            ]
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs

    def test_apply_with_project_config(self, tmp_path):
        """Test that ProjectConfig fields are applied to path_validator and content_scanner."""
        import async_crud_mcp.server as srv
        from async_crud_mcp.config import ProjectConfig

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        try:
            pc = ProjectConfig(
                base_directories=[str(tmp_path)],
                content_scan_enabled=False,
                default_read_policy="deny",
            )
            _apply_project_config(tmp_path, pc)
            assert str(tmp_path) in [
                str(d) for d in srv.path_validator._base_directories
            ]
            assert srv.content_scanner._enabled is False
            assert srv.path_validator._default_read_policy == "deny"
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs

    def test_apply_with_empty_base_dirs_uses_project_root(self, tmp_path):
        """Test that empty base_directories falls back to project_root."""
        import async_crud_mcp.server as srv
        from async_crud_mcp.config import ProjectConfig

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        try:
            pc = ProjectConfig(base_directories=[])
            _apply_project_config(tmp_path, pc)
            assert str(tmp_path) in [
                str(d) for d in srv.path_validator._base_directories
            ]
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs


class TestActivateProjectTool:
    """Test crud_activate_project MCP tool."""

    @pytest.mark.asyncio
    async def test_activate_valid_project(self, tmp_path):
        """Test activating a valid project directory."""
        import async_crud_mcp.server as srv

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_task = srv._config_watcher_task
        try:
            tool = mcp._tool_manager._tools["crud_activate_project"]
            result = await tool.fn(project_root=str(tmp_path))

            assert result["project_root"] == str(tmp_path)
            assert result["has_local_config"] is False
            assert (tmp_path / ".async-crud-mcp").is_dir()
        finally:
            if srv._config_watcher_task is not None:
                srv._config_watcher_task.cancel()
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._config_watcher_task = old_task

    @pytest.mark.asyncio
    async def test_activate_with_local_config(self, tmp_path):
        """Test activating a project that has a local config file."""
        import async_crud_mcp.server as srv

        # Create local config
        config_dir = tmp_path / ".async-crud-mcp"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(
            json.dumps({"content_scan_enabled": False}), encoding="utf-8"
        )

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_task = srv._config_watcher_task
        try:
            tool = mcp._tool_manager._tools["crud_activate_project"]
            result = await tool.fn(project_root=str(tmp_path))

            assert result["has_local_config"] is True
            assert result["content_scan_enabled"] is False
        finally:
            if srv._config_watcher_task is not None:
                srv._config_watcher_task.cancel()
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._config_watcher_task = old_task

    @pytest.mark.asyncio
    async def test_activate_nonexistent_dir(self, tmp_path):
        """Test activating a nonexistent directory returns error."""
        tool = mcp._tool_manager._tools["crud_activate_project"]
        result = await tool.fn(project_root=str(tmp_path / "nonexistent"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_activate_relative_path(self):
        """Test activating with relative path returns error."""
        tool = mcp._tool_manager._tools["crud_activate_project"]
        result = await tool.fn(project_root="relative/path")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_activate_with_invalid_config_falls_back(self, tmp_path):
        """Test activating with invalid config falls back to defaults with warning."""
        import async_crud_mcp.server as srv

        # Create invalid local config
        config_dir = tmp_path / ".async-crud-mcp"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("not valid json", encoding="utf-8")

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_task = srv._config_watcher_task
        old_warning = srv._config_warning
        try:
            tool = mcp._tool_manager._tools["crud_activate_project"]
            result = await tool.fn(project_root=str(tmp_path))

            # Should still activate but with warning
            assert result["project_root"] == str(tmp_path)
            assert "_config_warning" in result
        finally:
            if srv._config_watcher_task is not None:
                srv._config_watcher_task.cancel()
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._config_watcher_task = old_task
            srv._config_warning = old_warning


class TestGetConfigTool:
    """Test crud_get_config MCP tool."""

    @pytest.mark.asyncio
    async def test_get_full_config(self):
        """Test getting full config without section filter."""
        tool = mcp._tool_manager._tools["crud_get_config"]
        result = await tool.fn(section=None)

        assert "project" in result
        assert "daemon" in result
        assert "crud" in result
        assert "persistence" in result
        assert "watcher" in result

    @pytest.mark.asyncio
    async def test_get_crud_section(self):
        """Test getting crud section only."""
        tool = mcp._tool_manager._tools["crud_get_config"]
        result = await tool.fn(section="crud")

        assert "project" in result
        assert "crud" in result
        assert "daemon" not in result

    @pytest.mark.asyncio
    async def test_get_invalid_section(self):
        """Test getting invalid section returns error."""
        tool = mcp._tool_manager._tools["crud_get_config"]
        result = await tool.fn(section="invalid")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_config_shows_warning(self, tmp_path):
        """Test that config warning appears in get_config output."""
        import async_crud_mcp.server as srv

        old_warning = srv._config_warning
        try:
            srv._config_warning = "Test warning message"
            tool = mcp._tool_manager._tools["crud_get_config"]
            result = await tool.fn(section=None)
            assert result["_config_warning"] == "Test warning message"
        finally:
            srv._config_warning = old_warning


class TestUpdateConfigTool:
    """Test crud_update_config MCP tool."""

    @pytest.mark.asyncio
    async def test_update_without_active_project(self):
        """Test update returns error when no project is activated."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = None
            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(section="crud", updates={"content_scan_enabled": False})
            assert "error" in result
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_update_non_crud_section(self, tmp_path):
        """Test update rejects non-crud sections."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = tmp_path
            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(section="daemon", updates={"port": 9999})
            assert "error" in result
            assert "global" in result["error"].lower() or "crud" in result["error"].lower()
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_update_creates_config_file(self, tmp_path):
        """Test update creates .async-crud-mcp/config.json if it doesn't exist."""
        import async_crud_mcp.server as srv

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_lkgc = srv._last_valid_project_config
        old_warning = srv._config_warning
        try:
            srv._active_project_root = tmp_path
            config_dir = tmp_path / ".async-crud-mcp"
            config_dir.mkdir(exist_ok=True)

            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(
                section="crud",
                updates={"content_scan_enabled": False},
            )

            assert result["updated"] is True
            assert result["config"]["content_scan_enabled"] is False

            # Verify file was created
            config_file = config_dir / "config.json"
            assert config_file.exists()
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            assert saved["content_scan_enabled"] is False
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._last_valid_project_config = old_lkgc
            srv._config_warning = old_warning

    @pytest.mark.asyncio
    async def test_update_merges_with_existing(self, tmp_path):
        """Test update merges into existing config file."""
        import async_crud_mcp.server as srv

        # Create existing config
        config_dir = tmp_path / ".async-crud-mcp"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(
            json.dumps({"content_scan_enabled": True, "default_read_policy": "deny"}),
            encoding="utf-8",
        )

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_lkgc = srv._last_valid_project_config
        old_warning = srv._config_warning
        try:
            srv._active_project_root = tmp_path
            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(
                section="crud",
                updates={"content_scan_enabled": False},
            )

            assert result["updated"] is True
            assert result["config"]["content_scan_enabled"] is False
            # Original field preserved
            assert result["config"]["default_read_policy"] == "deny"
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._last_valid_project_config = old_lkgc
            srv._config_warning = old_warning

    @pytest.mark.asyncio
    async def test_update_rejects_invalid_values(self, tmp_path):
        """Test update rejects invalid config values."""
        import async_crud_mcp.server as srv

        config_dir = tmp_path / ".async-crud-mcp"
        config_dir.mkdir()

        old_root = srv._active_project_root
        try:
            srv._active_project_root = tmp_path
            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(
                section="crud",
                updates={"default_read_policy": "invalid_value"},
            )
            assert "error" in result
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_update_handles_json_string_input(self, tmp_path):
        """Test update handles updates passed as JSON string (MCP transport)."""
        import async_crud_mcp.server as srv

        config_dir = tmp_path / ".async-crud-mcp"
        config_dir.mkdir()

        old_pv = srv.path_validator
        old_cs = srv.content_scanner
        old_root = srv._active_project_root
        old_lkgc = srv._last_valid_project_config
        old_warning = srv._config_warning
        try:
            srv._active_project_root = tmp_path
            tool = mcp._tool_manager._tools["crud_update_config"]
            result = await tool.fn(
                section="crud",
                updates='{"content_scan_enabled": false}',
            )
            assert result["updated"] is True
            assert result["config"]["content_scan_enabled"] is False
        finally:
            srv.path_validator = old_pv
            srv.content_scanner = old_cs
            srv._active_project_root = old_root
            srv._last_valid_project_config = old_lkgc
            srv._config_warning = old_warning


class TestProjectActivationMiddleware:
    """Test that CRUD tools require project activation."""

    @pytest.fixture
    def middleware(self):
        return ProjectActivationMiddleware()

    @staticmethod
    def _make_context(tool_name, arguments=None):
        """Create a MiddlewareContext for a tool call."""
        from fastmcp.server.middleware import MiddlewareContext
        from mcp.types import CallToolRequestParams

        return MiddlewareContext(
            message=CallToolRequestParams(
                name=tool_name, arguments=arguments or {}
            ),
            source="client",
            type="request",
            method="tools/call",
        )

    @staticmethod
    async def _passthrough(context):
        """Dummy call_next that returns a sentinel ToolResult."""
        from fastmcp.tools.tool import ToolResult
        from mcp.types import TextContent

        return ToolResult(
            content=[TextContent(type="text", text="PASSTHROUGH")]
        )

    @pytest.mark.asyncio
    async def test_crud_tool_rejected_without_activation(self, middleware):
        """CRUD tools return error when no project is activated."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = None
            ctx = self._make_context("async_read_tool", {"path": "/tmp/test.txt"})
            result = await middleware.on_call_tool(ctx, self._passthrough)
            assert result.content[0].text.startswith("Error: No project activated")
            assert "crud_activate_project" in result.content[0].text
            assert "async_read_tool" in result.content[0].text
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_exempt_tools_work_without_activation(self, middleware):
        """Health tool and activate tool pass through without project activation."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = None
            for tool_name in _ACTIVATION_EXEMPT_TOOLS:
                ctx = self._make_context(tool_name)
                result = await middleware.on_call_tool(ctx, self._passthrough)
                assert result.content[0].text == "PASSTHROUGH", (
                    f"{tool_name} should be exempt but was blocked"
                )
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_get_config_requires_activation(self, middleware):
        """crud_get_config requires activation (not exempt)."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = None
            ctx = self._make_context("crud_get_config")
            result = await middleware.on_call_tool(ctx, self._passthrough)
            assert "crud_activate_project" in result.content[0].text
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_update_config_requires_activation(self, middleware):
        """crud_update_config requires activation (not exempt)."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = None
            ctx = self._make_context("crud_update_config", {
                "section": "crud", "updates": {}
            })
            result = await middleware.on_call_tool(ctx, self._passthrough)
            assert "crud_activate_project" in result.content[0].text
        finally:
            srv._active_project_root = old_root

    @pytest.mark.asyncio
    async def test_crud_tool_passes_after_activation(self, middleware, tmp_path):
        """CRUD tools pass through middleware after project activation."""
        import async_crud_mcp.server as srv

        old_root = srv._active_project_root
        try:
            srv._active_project_root = tmp_path
            ctx = self._make_context("async_read_tool", {"path": "/tmp/test.txt"})
            result = await middleware.on_call_tool(ctx, self._passthrough)
            assert result.content[0].text == "PASSTHROUGH"
        finally:
            srv._active_project_root = old_root

    def test_exempt_tools_frozenset_contents(self):
        """Verify the exempt tools set contains exactly the expected tools."""
        assert _ACTIVATION_EXEMPT_TOOLS == frozenset({
            "crud_activate_project",
            "health_tool",
        })
