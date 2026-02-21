"""FastMCP server module for async-crud-mcp.

This module provides the MCP server implementation with:
- SSE transport support (default port 8720)
- All 11 CRUD tools registered as @mcp.tool wrappers
- Health endpoint via dedicated MCP tool
- Port pre-flight validation before server start
- Shared dependency initialization (PathValidator, LockManager, HashRegistry)
- Per-project config activation with hot-reload and last-known-good fallback

Entry point: python -m async_crud_mcp.server
Referenced by bootstrap_daemon.py and dispatcher.py
"""

import asyncio
import contextlib
import json
import socket
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from loguru import logger
from mcp.types import TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse

from async_crud_mcp import __version__
from async_crud_mcp.config import (
    APP_NAME,
    PROJECT_CONFIG_DIR,
    PROJECT_CONFIG_FILE,
    ProjectConfig,
    get_settings,
    load_project_config,
)
from async_crud_mcp.core import (
    BackgroundTaskRegistry,
    ContentScanner,
    HashRegistry,
    LockManager,
    PathValidator,
    ShellProvider,
    ShellValidator,
)
from async_crud_mcp.daemon.config_watcher import ConfigWatcher, atomic_write_config
from async_crud_mcp.daemon.health import check_health
from async_crud_mcp.daemon.paths import get_config_file_path
from async_crud_mcp.models import (
    AsyncAppendRequest,
    AsyncBatchReadRequest,
    AsyncBatchUpdateRequest,
    AsyncBatchWriteRequest,
    AsyncDeleteRequest,
    AsyncListRequest,
    AsyncReadRequest,
    AsyncRenameRequest,
    AsyncStatusRequest,
    AsyncUpdateRequest,
    AsyncWriteRequest,
    BatchReadItem,
    BatchUpdateItem,
    BatchWriteItem,
    ExecRequest,
    Patch,
    SearchRequest,
    WaitRequest,
)
from async_crud_mcp.tools import (
    async_append,
    async_batch_read,
    async_batch_update,
    async_batch_write,
    async_delete,
    async_exec,
    async_list,
    async_read,
    async_rename,
    async_search,
    async_status,
    async_update,
    async_wait,
    async_write,
)

# Tools that work without project activation
_ACTIVATION_EXEMPT_TOOLS = frozenset({
    "crud_activate_project",  # The activation tool itself
    "health_tool",            # Health check is infrastructure, not project-scoped
})


class ProjectActivationMiddleware(Middleware):
    """Require crud_activate_project() before any CRUD tool call.

    Returns a clear error for non-exempt tools when no project is active,
    guiding the client to call crud_activate_project first.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> ToolResult:
        tool_name = context.message.name
        if tool_name not in _ACTIVATION_EXEMPT_TOOLS and _active_project_root is None:
            return ToolResult(
                content=[TextContent(
                    type="text",
                    text=(
                        f"Error: No project activated. "
                        f'Call crud_activate_project(project_root="/path/to/project") '
                        f"before using {tool_name}. "
                        f"This scopes CRUD operations to the project directory "
                        f"and loads any local .async-crud-mcp/config.json settings."
                    ),
                )],
            )
        return await call_next(context)


# Module-level shared dependencies (initialized once before tool registration)
# Load from global config file if it exists; fall back to defaults + env vars
# if the file is somehow unreadable.
try:
    _config_file = get_config_file_path()
    settings = get_settings(_config_file) if _config_file.exists() else get_settings()
except Exception as _init_err:
    logger.warning("Failed to load config file, using defaults: {}", _init_err)
    settings = get_settings()
path_validator = PathValidator(
    base_directories=settings.crud.base_directories,
    access_rules=settings.crud.access_rules,
    default_destructive_policy=settings.crud.default_destructive_policy,
    default_read_policy=settings.crud.default_read_policy,
)
lock_manager = LockManager(ttl_multiplier=settings.persistence.ttl_multiplier)
hash_registry = HashRegistry()
content_scanner = ContentScanner(
    rules=settings.crud.content_scan_rules,
    enabled=settings.crud.content_scan_enabled,
)
server_start_time = time.monotonic()  # Monotonic timestamp for async_status

# Shell extension dependencies
shell_provider = ShellProvider()
shell_validator = ShellValidator(settings.shell.deny_patterns)
background_registry = BackgroundTaskRegistry()


@contextlib.asynccontextmanager
async def _server_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Server lifespan handler for startup/shutdown of background services."""
    await background_registry.start()
    logger.info("Background task registry started")
    try:
        yield
    finally:
        await background_registry.shutdown()
        logger.info("Background task registry shut down")


# Initialize FastMCP server instance
mcp = FastMCP(APP_NAME, lifespan=_server_lifespan)
mcp.add_middleware(ProjectActivationMiddleware())

# Per-project activation state
_active_project_root: Path | None = None
_config_watcher_task: asyncio.Task | None = None
_last_valid_project_config: ProjectConfig | None = None
_config_warning: str | None = None  # Non-None when local config has parse errors


def _check_port_available(host: str, port: int) -> None:
    """Check if a TCP port is available for binding.

    Args:
        host: Host address to bind
        port: Port number to test

    Exits:
        With code 48 (EADDRINUSE) if port is already in use
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as e:
        logger.error(
            f"Port {port} is already in use on {host}. "
            f"Please choose a different port or stop the existing service. Error: {e}"
        )
        sys.exit(48)
    finally:
        sock.close()


# =============================================================================
# MCP Tool Wrappers (11 CRUD tools + 1 health tool)
# =============================================================================


@mcp.tool()
async def async_read_tool(
    path: str,
    offset: int = 0,
    limit: int | None = None,
    encoding: str = "utf-8",
):
    """Read file content with offset/limit support and hash computation.

    Args:
        path: File path to read
        offset: Line offset to start reading from (default: 0)
        limit: Maximum number of lines to read (default: None = all)
        encoding: File encoding (default: utf-8)

    Returns:
        ReadSuccessResponse with content and metadata, or ErrorResponse on failure
    """
    request = AsyncReadRequest(path=path, offset=offset, limit=limit, encoding=encoding)
    response = await async_read(request, path_validator, lock_manager, content_scanner)
    return response.model_dump()


@mcp.tool()
async def async_write_tool(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = True,
    timeout: float = 30.0,
):
    """Write content to a file atomically.

    Args:
        path: File path to write
        content: Content to write
        encoding: File encoding (default: utf-8)
        create_dirs: Create parent directories if missing (default: True)
        timeout: Operation timeout in seconds (default: 30.0)

    Returns:
        WriteSuccessResponse with file metadata, or ErrorResponse on failure
    """
    request = AsyncWriteRequest(
        path=path,
        content=content,
        encoding=encoding,
        create_dirs=create_dirs,
        timeout=timeout,
    )
    response = await async_write(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_update_tool(
    path: str,
    expected_hash: str,
    content: str | None = None,
    patches: list[dict] | None = None,
    encoding: str = "utf-8",
    timeout: float = 30.0,
    diff_format: str = "json",  # Will be validated by Pydantic
):
    """Update file content with conflict detection.

    Args:
        path: File path to update
        expected_hash: Expected file hash for conflict detection
        content: New file content (mutually exclusive with patches)
        patches: List of patch objects, each with 'old_string' and 'new_string' (mutually exclusive with content).
            Example: [{"old_string": "foo", "new_string": "bar"}]
        encoding: File encoding (default: utf-8)
        timeout: Operation timeout in seconds (default: 30.0)
        diff_format: Diff format for contention responses (default: json)

    Returns:
        UpdateSuccessResponse or UpdateContentionResponse or ErrorResponse
    """
    # Guard: MCP transport may serialize list params as JSON strings
    if patches is not None and isinstance(patches, str):
        patches = json.loads(patches)

    # Convert patches dict to Patch objects if provided
    patches_obj = None
    if patches is not None:
        patches_obj = [Patch(**p) for p in patches]

    # Validate diff_format
    if diff_format not in ("json", "unified"):
        diff_format = "json"

    request = AsyncUpdateRequest(
        path=path,
        expected_hash=expected_hash,
        content=content,
        patches=patches_obj,
        encoding=encoding,
        timeout=timeout,
        diff_format=diff_format,  # type: ignore[arg-type]  # Validated above
    )
    response = await async_update(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_delete_tool(path: str, timeout: float = 30.0):
    """Delete a file.

    Args:
        path: File path to delete
        timeout: Operation timeout in seconds (default: 30.0)

    Returns:
        DeleteSuccessResponse with deletion timestamp, or ErrorResponse on failure
    """
    request = AsyncDeleteRequest(path=path, timeout=timeout)
    response = await async_delete(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_rename_tool(
    old_path: str,
    new_path: str,
    timeout: float = 30.0,
):
    """Rename a file.

    Args:
        old_path: Current file path
        new_path: New file path
        timeout: Operation timeout in seconds (default: 30.0)

    Returns:
        RenameSuccessResponse with new hash, or ErrorResponse on failure
    """
    request = AsyncRenameRequest(old_path=old_path, new_path=new_path, timeout=timeout)
    response = await async_rename(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_append_tool(
    path: str,
    content: str,
    encoding: str = "utf-8",
    timeout: float = 30.0,
    create_if_missing: bool = False,
    create_dirs: bool = True,
    separator: str = "",
):
    """Append content to a file.

    Args:
        path: File path to append to
        content: Content to append
        encoding: File encoding (default: utf-8)
        timeout: Operation timeout in seconds (default: 30.0)
        create_if_missing: Create file if it does not exist (default: False)
        create_dirs: Create parent directories if missing (default: True)
        separator: Separator to insert before content (default: empty)

    Returns:
        AppendSuccessResponse with new hash, or ErrorResponse on failure
    """
    # Decode common escape sequences in separator (MCP transport delivers literal strings)
    if separator:
        separator = separator.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    request = AsyncAppendRequest(
        path=path,
        content=content,
        encoding=encoding,
        timeout=timeout,
        create_if_missing=create_if_missing,
        create_dirs=create_dirs,
        separator=separator,
    )
    response = await async_append(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_list_tool(
    path: str,
    recursive: bool = False,
    pattern: str = "*",
    include_hashes: bool = False,
):
    """List directory contents.

    Args:
        path: Directory path to list
        recursive: List recursively (default: False)
        pattern: Glob pattern to filter entries (default: *)
        include_hashes: Include file hashes in response (default: False)

    Returns:
        ListSuccessResponse with file/directory entries, or ErrorResponse on failure
    """
    request = AsyncListRequest(
        path=path,
        recursive=recursive,
        pattern=pattern,
        include_hashes=include_hashes,
    )
    response = await async_list(request, path_validator, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_status_tool(path: str | None = None):
    """Get file status or global server status.

    Args:
        path: File path to check status, or omit for global server status

    Returns:
        FileStatusResponse if path provided, GlobalStatusResponse if omitted, or ErrorResponse on failure
    """
    request = AsyncStatusRequest(path=path)
    response = await async_status(
        request,
        path_validator,
        lock_manager,
        hash_registry,
        settings,
        server_start_time,
    )
    return response.model_dump()


@mcp.tool()
async def async_batch_read_tool(files: list[dict]):
    """Batch read multiple files.

    Args:
        files: List of read operation objects. Each must have 'path'; optional: 'offset', 'limit', 'encoding'.
            Example: [{"path": "/tmp/a.txt"}, {"path": "/tmp/b.txt", "offset": 10, "limit": 50}]

    Returns:
        BatchReadResponse with results for each file
    """
    # Guard: MCP transport may serialize list params as JSON strings
    if isinstance(files, str):
        files = json.loads(files)

    # Convert dict operations to BatchReadItem objects
    read_items = [BatchReadItem(**op) for op in files]

    request = AsyncBatchReadRequest(files=read_items)
    response = await async_batch_read(request, path_validator, lock_manager, content_scanner)
    return response.model_dump()


@mcp.tool()
async def async_batch_write_tool(files: list[dict]):
    """Batch write multiple files.

    Args:
        files: List of write operation objects. Each must have 'path' and 'content'; optional: 'encoding', 'create_dirs'.
            Example: [{"path": "/tmp/a.txt", "content": "hello"}, {"path": "/tmp/b.txt", "content": "world"}]

    Returns:
        BatchWriteResponse with results for each file
    """
    # Guard: MCP transport may serialize list params as JSON strings
    if isinstance(files, str):
        files = json.loads(files)

    # Convert dict operations to BatchWriteItem objects
    write_items = [BatchWriteItem(**op) for op in files]

    request = AsyncBatchWriteRequest(files=write_items)
    response = await async_batch_write(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_batch_update_tool(files: list[dict]):
    """Batch update multiple files with conflict detection.

    Args:
        files: List of update operation objects. Each must have 'path' and 'expected_hash'; provide 'content' OR 'patches'.
            Example: [{"path": "/tmp/a.txt", "expected_hash": "abc123", "content": "new content"}]
            Patch example: [{"path": "/tmp/a.txt", "expected_hash": "abc123", "patches": [{"old_string": "foo", "new_string": "bar"}]}]

    Returns:
        BatchUpdateResponse with results for each file
    """
    # Guard: MCP transport may serialize list params as JSON strings
    if isinstance(files, str):
        files = json.loads(files)

    # Convert dict operations to BatchUpdateItem objects
    update_items = []
    for op in files:
        # Convert patches dict to Patch objects if provided
        patches_obj = None
        if op.get("patches") is not None:
            patches_obj = [Patch(**p) for p in op["patches"]]
            op = {**op, "patches": patches_obj}

        update_items.append(BatchUpdateItem(**op))

    request = AsyncBatchUpdateRequest(files=update_items)
    response = await async_batch_update(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def health_tool():
    """Check the health status of the daemon.

    Returns:
        Health check results with status, version, uptime, config, logs, and port connectivity
    """
    health_data = check_health()
    # Enrich response with version and uptime
    health_data["version"] = __version__
    health_data["uptime"] = time.monotonic() - server_start_time
    return health_data


# =============================================================================
# Shell extension MCP tools (3 tools)
# =============================================================================


@mcp.tool()
async def async_exec_tool(
    command: str,
    timeout: float = 30.0,
    cwd: str | None = None,
    env: dict | None = None,
    background: bool = False,
):
    """Execute a shell command with policy enforcement.

    Commands are validated against deny patterns before execution.
    File I/O commands (cat, sed, rm, etc.) are denied -- use CRUD tools instead.
    Legitimate commands (git, pytest, npm, pip, etc.) are allowed.

    Args:
        command: Shell command to execute (passed to bash -c)
        timeout: Command timeout in seconds (default: 30, max: 300)
        cwd: Working directory (default: project root)
        env: Additional environment variables to set
        background: If true, run in background and return task_id immediately

    Returns:
        ExecSuccessResponse (foreground), ExecBackgroundResponse (background),
        ExecDeniedResponse (blocked by policy), or ErrorResponse on failure
    """
    # Guard: MCP transport may serialize dict params as JSON strings
    if env is not None and isinstance(env, str):
        env = json.loads(env)

    # Resolve effective shell config (project override for enabled)
    effective_config = settings.shell
    if _last_valid_project_config is not None:
        if _last_valid_project_config.shell_enabled is not None:
            effective_config = effective_config.model_copy(
                update={"enabled": _last_valid_project_config.shell_enabled}
            )

    request = ExecRequest(
        command=command,
        timeout=timeout,
        cwd=cwd,
        env=env,
        background=background,
    )
    response = await async_exec(
        request,
        shell_config=effective_config,
        shell_provider=shell_provider,
        shell_validator=shell_validator,
        background_registry=background_registry,
        project_root=_active_project_root,
    )
    return response.model_dump()


@mcp.tool()
async def async_wait_tool(
    seconds: float = 0.0,
    task_id: str | None = None,
):
    """Wait for a duration or background task completion.

    If task_id is provided, waits for that background task to finish
    (up to 'seconds' timeout, default 30s). Otherwise, simply sleeps.

    Args:
        seconds: Seconds to sleep, or timeout when waiting for a task (default: 0)
        task_id: Background task ID to wait for (from async_exec_tool with background=True)

    Returns:
        WaitResponse with waited duration and optional task result, or ErrorResponse
    """
    request = WaitRequest(seconds=seconds, task_id=task_id)
    response = await async_wait(request, background_registry)
    return response.model_dump()


@mcp.tool()
async def async_search_tool(
    pattern: str,
    path: str | None = None,
    glob: str = "*",
    recursive: bool = True,
    case_insensitive: bool = False,
    max_results: int = 100,
    context_lines: int = 0,
    output_mode: str = "content",
):
    """Search file contents by regex pattern.

    Searches files matching the glob pattern for lines matching the regex.
    Respects access control rules and content scanning policies.

    Args:
        pattern: Regex pattern to search for
        path: Search directory (default: project root)
        glob: Glob pattern to filter files (default: *)
        recursive: Search subdirectories (default: True)
        case_insensitive: Case-insensitive matching (default: False)
        max_results: Maximum matches to return (default: 100)
        context_lines: Lines of context before/after each match (default: 0)
        output_mode: 'content' (default), 'files_with_matches', or 'count'

    Returns:
        SearchResponse with matches, or ErrorResponse on failure
    """
    # Validate output_mode
    if output_mode not in ("content", "files_with_matches", "count"):
        output_mode = "content"

    request = SearchRequest(
        pattern=pattern,
        path=path,
        glob=glob,
        recursive=recursive,
        case_insensitive=case_insensitive,
        max_results=max_results,
        context_lines=context_lines,
        output_mode=output_mode,  # type: ignore[arg-type]
    )
    response = await async_search(
        request,
        search_config=settings.search,
        path_validator=path_validator,
        content_scanner=content_scanner,
        project_root=_active_project_root,
    )
    return response.model_dump()


@mcp.custom_route("/health", methods=["GET"])
async def health_http_endpoint(request: Request) -> JSONResponse:
    """HTTP GET /health endpoint for plain HTTP health checks.

    Returns JSON with status, version, uptime, and daemon health fields.
    HTTP 200 for healthy/degraded status, HTTP 503 for unhealthy.
    """
    health_data = check_health()
    health_data["version"] = __version__
    health_data["uptime"] = time.monotonic() - server_start_time
    status_code = 503 if health_data.get("status") == "unhealthy" else 200
    return JSONResponse(health_data, status_code=status_code)


# =============================================================================
# Project config helpers
# =============================================================================


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base dict. Lists are replaced, not appended."""
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_project_config(
    project_root: Path,
    project_config: ProjectConfig | None = None,
) -> None:
    """Rebuild path_validator, content_scanner, and shell_validator from project config.

    Args:
        project_root: Project directory (used as fallback base_directory).
        project_config: Local config, or None to use global defaults with
            project_root as base_dir.
    """
    global path_validator, content_scanner

    if project_config is not None:
        base_dirs = project_config.base_directories or [str(project_root)]
        path_validator = PathValidator(
            base_directories=base_dirs,
            access_rules=project_config.access_rules,
            default_destructive_policy=project_config.default_destructive_policy,
            default_read_policy=project_config.default_read_policy,
        )
        content_scanner = ContentScanner(
            rules=project_config.content_scan_rules,
            enabled=project_config.content_scan_enabled,
        )
        # Rebuild shell deny patterns from project config
        if project_config.shell_deny_patterns_mode == "replace":
            shell_validator.reload(project_config.shell_deny_patterns)
        else:
            merged = list(settings.shell.deny_patterns) + list(project_config.shell_deny_patterns)
            shell_validator.reload(merged)
    else:
        path_validator = PathValidator(
            base_directories=[str(project_root)],
            access_rules=settings.crud.access_rules,
            default_destructive_policy=settings.crud.default_destructive_policy,
            default_read_policy=settings.crud.default_read_policy,
        )
        content_scanner = ContentScanner(
            rules=settings.crud.content_scan_rules,
            enabled=settings.crud.content_scan_enabled,
        )
        # Reset shell validator to global defaults
        shell_validator.reload(settings.shell.deny_patterns)


def _get_config_warning() -> dict | None:
    """Return a config warning dict if a parse error is active, else None."""
    if _config_warning is not None:
        return {"_config_warning": _config_warning}
    return None


async def _config_watch_loop() -> None:
    """Background task that polls the local project config for changes.

    Uses ConfigWatcher for debounced change detection and maintains a
    last-known-good config fallback when the file contains errors.
    """
    global _last_valid_project_config, _config_warning

    if _active_project_root is None:
        return

    config_path = _active_project_root / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    watcher = ConfigWatcher(
        config_path,
        poll_seconds=settings.daemon.config_poll_seconds,
        debounce_seconds=settings.daemon.config_debounce_seconds,
    )
    watcher.reset()

    while True:
        await asyncio.sleep(watcher.poll_seconds)
        if watcher.check_for_changes():
            logger.info("Project config changed, hot-reloading CRUD policy")
            try:
                project_config = load_project_config(_active_project_root)
                _apply_project_config(_active_project_root, project_config)
                if project_config is not None:
                    _last_valid_project_config = project_config
                _config_warning = None
                watcher.reset()
                logger.info("Project config reloaded successfully")
            except Exception as e:
                msg = f"Project config reload failed: {e}"
                logger.error(msg)
                _config_warning = msg
                # Fall back to last known good config
                if _last_valid_project_config is not None:
                    logger.info("Using last-known-good project config")
                    _apply_project_config(
                        _active_project_root, _last_valid_project_config
                    )
                watcher.reset()


# =============================================================================
# Project config MCP tools
# =============================================================================


@mcp.tool(name="crud_activate_project")
async def activate_project_tool(project_root: str) -> dict:
    """Activate a project directory for CRUD operations.

    Loads per-project configuration from {project_root}/.async-crud-mcp/config.json
    if it exists. This overrides global CRUD policy (access rules, content scan rules,
    base directories) with project-specific settings.

    Call this once at the start of a session when working in a specific project.
    If no local config exists, the project root is used as the sole base directory
    with global defaults.

    Args:
        project_root: Absolute path to the project root directory.

    Returns:
        Activation result with effective config summary.
    """
    global _active_project_root, _config_watcher_task
    global _last_valid_project_config, _config_warning

    root = Path(project_root)
    if not root.is_absolute():
        return {"error": "project_root must be an absolute path"}
    if not root.is_dir():
        return {"error": f"Directory does not exist: {project_root}"}

    _active_project_root = root
    _config_warning = None

    # Create .async-crud-mcp/ dir if it doesn't exist (but not the config file)
    config_dir = root / PROJECT_CONFIG_DIR
    config_dir.mkdir(exist_ok=True)

    # Load local config
    has_local_config = False
    try:
        project_config = load_project_config(root)
        has_local_config = project_config is not None
        _apply_project_config(root, project_config)
        if project_config is not None:
            _last_valid_project_config = project_config
    except Exception as e:
        msg = f"Failed to load project config: {e}"
        logger.error(msg)
        _config_warning = msg
        # Apply defaults with project root as base
        _apply_project_config(root, None)

    # Start/restart config watcher
    if _config_watcher_task is not None:
        _config_watcher_task.cancel()
    _config_watcher_task = asyncio.create_task(_config_watch_loop())

    result = {
        "project_root": str(root),
        "has_local_config": has_local_config,
        "config_dir": str(config_dir),
        "effective_base_directories": [str(d) for d in path_validator._base_directories],
        "access_rules_count": len(path_validator._access_rules),
        "content_scan_enabled": content_scanner._enabled,
    }
    if _config_warning:
        result["_config_warning"] = _config_warning
    return result


@mcp.tool(name="crud_get_config")
async def get_config_tool(section: str | None = None) -> dict:
    """Read the effective CRUD configuration for the active project.

    Returns the merged configuration (global defaults + local project overrides).
    Use this to inspect current settings before making changes with crud_update_config.

    Args:
        section: Optional section to return ('crud', 'daemon', 'persistence', 'watcher').
                 If omitted, returns the full effective config plus project info.

    Returns:
        Configuration dict with project activation status.
    """
    valid_sections = ("crud", "daemon", "persistence", "watcher", "shell", "search")

    if section is not None and section not in valid_sections:
        return {"error": f"Invalid section '{section}'. Valid: {', '.join(valid_sections)}"}

    # Build project info
    project_info: dict = {
        "project_root": str(_active_project_root) if _active_project_root else None,
        "has_local_config": False,
    }
    if _active_project_root is not None:
        config_path = _active_project_root / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
        project_info["has_local_config"] = config_path.exists()

    # Build config sections
    sections = {
        "daemon": settings.daemon.model_dump(),
        "crud": settings.crud.model_dump(),
        "persistence": settings.persistence.model_dump(),
        "watcher": settings.watcher.model_dump(),
        "shell": settings.shell.model_dump(),
        "search": settings.search.model_dump(),
    }

    # If a project is active with local config, overlay project config into crud section
    if _active_project_root is not None and _last_valid_project_config is not None:
        sections["crud"] = _deep_merge(
            sections["crud"],
            _last_valid_project_config.model_dump(exclude_defaults=True),
        )

    if section is not None:
        result = {"project": project_info, section: sections[section]}
    else:
        result = {"project": project_info, **sections}

    warning = _get_config_warning()
    if warning:
        result.update(warning)
    return result


@mcp.tool(name="crud_update_config")
async def update_config_tool(section: str, updates: dict) -> dict:
    """Update the local project CRUD configuration and persist to disk.

    IMPORTANT: This tool modifies the project's .async-crud-mcp/config.json file.
    Do NOT call this tool unless the user has explicitly requested a configuration
    change. Always confirm with the user before invoking.

    Only the 'crud' section can be updated via this tool (project-scoped settings).
    Daemon settings (port, host, transport) are global and must be changed via CLI.

    Performs a shallow merge of updates into the local config, validates the
    result, writes atomically, and triggers an immediate hot-reload.

    Args:
        section: Must be 'crud' (only project-scoped settings are writable).
        updates: Partial dict to merge into the crud config.
            Example: {"content_scan_enabled": false}
            Example: {"access_rules": [...], "default_read_policy": "deny"}

    Returns:
        Updated local config after merge, or error dict on failure.
    """
    global _last_valid_project_config, _config_warning

    if _active_project_root is None:
        return {"error": "No project activated. Call crud_activate_project first."}

    if section != "crud":
        return {
            "error": f"Only 'crud' section can be updated via this tool. "
            f"'{section}' settings are global and must be changed via CLI."
        }

    # Guard: MCP transport may serialize dict params as JSON strings
    if isinstance(updates, str):
        updates = json.loads(updates)

    # Load current local config file (or empty dict if doesn't exist)
    config_path = _active_project_root / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    if config_path.exists():
        try:
            current = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return {"error": f"Failed to read current config: {e}"}
    else:
        current = {}

    # Merge updates
    merged = _deep_merge(current, updates)

    # Validate against ProjectConfig model
    try:
        validated = ProjectConfig.model_validate(merged)
    except Exception as e:
        return {"error": f"Validation failed: {e}"}

    # Write atomically - create directory if needed
    config_dir = _active_project_root / PROJECT_CONFIG_DIR
    config_dir.mkdir(exist_ok=True)
    try:
        atomic_write_config(config_path, merged)
    except OSError as e:
        return {"error": f"Failed to write config: {e}"}

    # Immediate hot-reload
    _last_valid_project_config = validated
    _config_warning = None
    _apply_project_config(_active_project_root, validated)

    result = {"updated": True, "config": validated.model_dump()}
    return result


# =============================================================================
# Main entry point
# =============================================================================

def main():
    """Entry point for the MCP server.

    Called by dispatcher (``from async_crud_mcp.server import main; main()``)
    and also via ``python -m async_crud_mcp.server``.
    """
    host = settings.daemon.host
    port = settings.daemon.port or 8720  # Default to 8720 if None

    # Security warning for non-localhost binding
    if host not in ("127.0.0.1", "::1", "localhost"):
        logger.warning(
            f"Security: binding to non-localhost address {host} exposes the server to network access"
        )

    _check_port_available(host, port)

    # Start server with configured transport
    mcp.run(
        transport=settings.daemon.transport,
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
