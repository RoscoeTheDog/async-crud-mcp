"""FastMCP server module for async-crud-mcp.

This module provides the MCP server implementation with:
- SSE transport support (default port 8720)
- All 11 CRUD tools registered as @mcp.tool wrappers
- Health endpoint via dedicated MCP tool
- Port pre-flight validation before server start
- Shared dependency initialization (PathValidator, LockManager, HashRegistry)

Entry point: python -m async_crud_mcp.server
Referenced by bootstrap_daemon.py and windows/dispatcher.py
"""

import socket
import sys
import time

from fastmcp import FastMCP
from loguru import logger

from async_crud_mcp import __version__
from async_crud_mcp.config import APP_NAME, get_settings
from async_crud_mcp.core import HashRegistry, LockManager, PathValidator
from async_crud_mcp.daemon.health import check_health
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
    Patch,
)
from async_crud_mcp.tools import (
    async_append,
    async_batch_read,
    async_batch_update,
    async_batch_write,
    async_delete,
    async_list,
    async_read,
    async_rename,
    async_status,
    async_update,
    async_write,
)

# Initialize FastMCP server instance
mcp = FastMCP(APP_NAME)

# Module-level shared dependencies (initialized once before tool registration)
settings = get_settings()
path_validator = PathValidator(
    base_directories=settings.crud.base_directories,
    access_rules=settings.crud.access_rules,
    default_destructive_policy=settings.crud.default_destructive_policy,
)
lock_manager = LockManager(ttl_multiplier=settings.persistence.ttl_multiplier)
hash_registry = HashRegistry()
server_start_time = time.time()  # Monotonic timestamp for async_status


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
    response = await async_read(request, path_validator, lock_manager)
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
        patches: List of patches to apply (mutually exclusive with content)
        encoding: File encoding (default: utf-8)
        timeout: Operation timeout in seconds (default: 30.0)
        diff_format: Diff format for contention responses (default: json)

    Returns:
        UpdateSuccessResponse or UpdateContentionResponse or ErrorResponse
    """
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
async def async_status_tool(path: str):
    """Get file status and lock information.

    Args:
        path: File path to check status

    Returns:
        StatusSuccessResponse with file metadata and lock info, or ErrorResponse on failure
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
        files: List of read operation dicts with 'path', 'offset', 'limit', 'encoding' fields

    Returns:
        BatchReadResponse with results for each operation
    """
    # Convert dict operations to BatchReadItem objects
    read_items = [BatchReadItem(**op) for op in files]

    request = AsyncBatchReadRequest(files=read_items)
    response = await async_batch_read(request, path_validator, lock_manager)
    return response.model_dump()


@mcp.tool()
async def async_batch_write_tool(files: list[dict]):
    """Batch write multiple files.

    Args:
        files: List of write operation dicts with 'path', 'content', 'encoding', 'create_dirs' fields

    Returns:
        BatchWriteResponse with results for each operation
    """
    # Convert dict operations to BatchWriteItem objects
    write_items = [BatchWriteItem(**op) for op in files]

    request = AsyncBatchWriteRequest(files=write_items)
    response = await async_batch_write(request, path_validator, lock_manager, hash_registry)
    return response.model_dump()


@mcp.tool()
async def async_batch_update_tool(files: list[dict]):
    """Batch update multiple files.

    Args:
        files: List of update operation dicts with 'path', 'expected_hash', 'content', 'patches', 'encoding' fields

    Returns:
        BatchUpdateResponse with results for each operation
    """
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
    health_data["uptime"] = time.time() - server_start_time
    return health_data


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    # Port pre-flight check
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
