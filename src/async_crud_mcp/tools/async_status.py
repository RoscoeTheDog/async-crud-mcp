"""Async status tool for querying server and per-file status."""

import os
import time
from typing import Union

from async_crud_mcp import __version__
from async_crud_mcp.config import Settings
from async_crud_mcp.core import HashRegistry, LockManager, PathValidationError, PathValidator
from async_crud_mcp.models import (
    ActiveLocks,
    AsyncStatusRequest,
    ErrorCode,
    ErrorResponse,
    FileStatusResponse,
    GlobalStatusResponse,
    PendingRequest,
    ServerInfo,
)


async def async_status(
    request: AsyncStatusRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
    settings: Settings,
    server_start_time: float,
) -> Union[GlobalStatusResponse, FileStatusResponse, ErrorResponse]:
    """
    Query server global status or per-file status.

    Args:
        request: Status request with optional path field
        path_validator: PathValidator instance for path validation
        lock_manager: LockManager instance for lock status
        hash_registry: HashRegistry instance for tracked files
        settings: Settings instance for server configuration
        server_start_time: Server start time (monotonic timestamp)

    Returns:
        GlobalStatusResponse if path is None, FileStatusResponse if path is provided,
        or ErrorResponse on failure
    """
    try:
        # Global status (path is None)
        if request.path is None:
            # Build ServerInfo
            uptime_seconds = time.monotonic() - server_start_time
            persistence_mode = "enabled" if settings.persistence.enabled else "disabled"

            server_info = ServerInfo(
                version=__version__,
                uptime_seconds=uptime_seconds,
                transport=settings.daemon.transport,
                port=settings.daemon.port or 0,  # Use 0 if None (auto-assigned)
                persistence=persistence_mode,
            )

            # Count tracked files from HashRegistry
            tracked_files = len(hash_registry.snapshot())

            # Count active locks from LockManager
            all_lock_status = lock_manager.get_all_status()
            read_count = 0
            write_count = 0
            total_queue_depth = 0

            for lock_status in all_lock_status:
                read_count += lock_status["active_readers"]
                if lock_status["active_writer"]:
                    write_count += 1
                total_queue_depth += lock_status["queued"]

            active_locks = ActiveLocks(
                read=read_count,
                write=write_count,
            )

            return GlobalStatusResponse(
                server=server_info,
                tracked_files=tracked_files,
                active_locks=active_locks,
                queue_depth=total_queue_depth,
                base_directories=settings.crud.base_directories,
            )

        # Per-file status (path is provided)
        else:
            # Validate path
            try:
                validated_path = path_validator.validate(request.path)
            except PathValidationError as e:
                return ErrorResponse(
                    error_code=ErrorCode.PATH_OUTSIDE_BASE,
                    message=str(e),
                    path=request.path,
                )

            # Check if file exists
            exists = os.path.exists(validated_path)

            # Get hash from HashRegistry
            file_hash = hash_registry.get(str(validated_path)) if exists else None

            # Get lock status from LockManager
            lock_status = lock_manager.get_status(str(validated_path))

            # Derive lock_state string
            if lock_status["active_writer"]:
                lock_state = "write_locked"
            elif lock_status["active_readers"] > 0:
                lock_state = "read_locked"
            else:
                lock_state = "unlocked"

            # Build pending_requests list
            # Note: Current LockManager.get_status only returns queued count, not queue details
            # For now, we'll return an empty list since we don't have access to queue details
            # This could be extended in the future by adding a method to expose queue entries
            pending_requests: list[PendingRequest] = []

            return FileStatusResponse(
                path=str(validated_path),
                exists=exists,
                hash=file_hash,
                lock_state=lock_state,
                queue_depth=lock_status["queued"],
                active_readers=lock_status["active_readers"],
                pending_requests=pending_requests,
            )

    except Exception as e:
        # Catch-all for unexpected errors
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message=f"Unexpected error during status: {e}",
            path=request.path,
        )
