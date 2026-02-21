"""Response models for async-crud-mcp MCP tools.

All response models use Pydantic v2 BaseModel with frozen=True for immutability.
"""

from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Error codes for async-crud-mcp operations."""

    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_EXISTS = "FILE_EXISTS"
    ACCESS_DENIED = "ACCESS_DENIED"
    PATH_OUTSIDE_BASE = "PATH_OUTSIDE_BASE"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    ENCODING_ERROR = "ENCODING_ERROR"
    INVALID_PATCH = "INVALID_PATCH"
    CONTENT_OR_PATCHES_REQUIRED = "CONTENT_OR_PATCHES_REQUIRED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    WRITE_ERROR = "WRITE_ERROR"
    DELETE_ERROR = "DELETE_ERROR"
    RENAME_ERROR = "RENAME_ERROR"
    DIR_NOT_FOUND = "DIR_NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"
    COMMAND_DENIED = "COMMAND_DENIED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    SHELL_DISABLED = "SHELL_DISABLED"
    SEARCH_DISABLED = "SEARCH_DISABLED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    INVALID_PATTERN = "INVALID_PATTERN"


# Success Response Models


class ReadSuccessResponse(BaseModel):
    """Success response for async_read tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was read")
    content: str = Field(..., description="File content")
    encoding: str = Field(..., description="File encoding used")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    total_lines: int = Field(..., description="Total number of lines in file")
    offset: int = Field(..., description="Line offset used")
    limit: int | None = Field(..., description="Line limit used")
    lines_returned: int = Field(..., description="Number of lines returned")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class WriteSuccessResponse(BaseModel):
    """Success response for async_write tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was written")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    bytes_written: int = Field(..., description="Number of bytes written")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class UpdateSuccessResponse(BaseModel):
    """Success response for async_update tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was updated")
    previous_hash: str = Field(..., description="Hash before update")
    hash: str = Field(..., description="Hash after update (format: sha256:...)")
    bytes_written: int = Field(..., description="Number of bytes written")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class DeleteSuccessResponse(BaseModel):
    """Success response for async_delete tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was deleted")
    deleted_hash: str = Field(..., description="Hash of deleted file")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class RenameSuccessResponse(BaseModel):
    """Success response for async_rename tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    old_path: str = Field(..., description="Original file path")
    new_path: str = Field(..., description="New file path")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")
    cross_filesystem: bool = Field(default=False, description="Whether rename crossed filesystem boundaries")


class AppendSuccessResponse(BaseModel):
    """Success response for async_append tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was appended to")
    hash: str = Field(..., description="File content hash after append (format: sha256:...)")
    bytes_appended: int = Field(..., description="Number of bytes appended")
    total_size_bytes: int = Field(..., description="Total file size after append")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class DirectoryEntry(BaseModel):
    """A single directory entry in list results."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Entry name")
    type: Literal["file", "directory"] = Field(..., description="Entry type")
    size_bytes: int | None = Field(default=None, description="File size in bytes (None for directories)")
    modified: str | None = Field(default=None, description="Last modified timestamp (ISO 8601)")
    hash: str | None = Field(default=None, description="File hash if include_hashes=True")


class ListSuccessResponse(BaseModel):
    """Success response for async_list tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="Directory path that was listed")
    entries: list[DirectoryEntry] = Field(..., description="Directory entries")
    total_entries: int = Field(..., description="Total number of entries")
    pattern: str = Field(..., description="Glob pattern used")
    recursive: bool = Field(..., description="Whether recursive listing was used")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


# Error Response Model


class ErrorResponse(BaseModel):
    """Error response for any operation."""

    model_config = ConfigDict(frozen=True)

    status: Literal["error"] = "error"
    error_code: ErrorCode = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    path: str | None = Field(default=None, description="File path related to error")
    details: dict | None = Field(default=None, description="Additional error details")


# Contention Response Models


class DiffChange(BaseModel):
    """A single change in a diff."""

    model_config = ConfigDict(frozen=True)

    type: Literal["added", "removed", "modified"] = Field(..., description="Change type")
    start_line: int = Field(..., description="Starting line number")
    end_line: int | None = Field(default=None, description="Ending line number (for multi-line changes)")
    old_content: str | None = Field(default=None, description="Original content (for removed/modified)")
    new_content: str | None = Field(default=None, description="New content (for added/modified)")
    context_before: str | None = Field(default=None, description="Context lines before change")
    context_after: str | None = Field(default=None, description="Context lines after change")


class DiffSummary(BaseModel):
    """Summary of diff changes."""

    model_config = ConfigDict(frozen=True)

    lines_added: int = Field(..., description="Number of lines added")
    lines_removed: int = Field(..., description="Number of lines removed")
    lines_modified: int = Field(..., description="Number of lines modified")
    regions_changed: int = Field(..., description="Number of change regions")


class JsonDiff(BaseModel):
    """JSON-formatted diff."""

    model_config = ConfigDict(frozen=True)

    format: Literal["json"] = "json"
    changes: list[DiffChange] = Field(..., description="List of changes")
    summary: DiffSummary = Field(..., description="Diff summary")


class UnifiedDiff(BaseModel):
    """Unified diff format."""

    model_config = ConfigDict(frozen=True)

    format: Literal["unified"] = "unified"
    content: str = Field(..., description="Unified diff content")
    summary: DiffSummary = Field(..., description="Diff summary")


class PatchConflict(BaseModel):
    """A patch that could not be applied."""

    model_config = ConfigDict(frozen=True)

    patch_index: int = Field(..., description="Index of conflicting patch")
    reason: str = Field(..., description="Reason patch could not be applied")


class ContentionResponse(BaseModel):
    """Contention response for update/delete/rename operations."""

    model_config = ConfigDict(frozen=True)

    status: Literal["contention"] = "contention"
    path: str = Field(..., description="File path with contention")
    expected_hash: str = Field(..., description="Hash that was expected")
    current_hash: str = Field(..., description="Current file hash")
    message: str = Field(..., description="Human-readable contention message")
    diff: Annotated[JsonDiff | UnifiedDiff, Field(discriminator="format")] = Field(..., description="Diff showing changes")
    patches_applicable: bool | None = Field(default=None, description="Whether patches can still be applied (update only)")
    conflicts: list[PatchConflict] | None = Field(default=None, description="Conflicting patches (update only)")
    non_conflicting_patches: list[int] | None = Field(default=None, description="Indices of non-conflicting patches")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


# Status Response Models


class ServerInfo(BaseModel):
    """Server information."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(..., description="Server version")
    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    transport: str = Field(..., description="Transport protocol")
    port: int = Field(..., description="Server port")
    persistence: str = Field(..., description="Persistence mode")


class ActiveLocks(BaseModel):
    """Active lock counts."""

    model_config = ConfigDict(frozen=True)

    read: int = Field(..., description="Number of active read locks")
    write: int = Field(..., description="Number of active write locks")


class GlobalStatusResponse(BaseModel):
    """Global status response (path=None)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    server: ServerInfo = Field(..., description="Server information")
    tracked_files: int = Field(..., description="Number of tracked files")
    active_locks: ActiveLocks = Field(..., description="Active lock counts")
    queue_depth: int = Field(..., description="Request queue depth")
    base_directories: list[str] = Field(..., description="Base directories")


class PendingRequest(BaseModel):
    """A pending request in the queue."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(..., description="Request type")
    queued_at: str = Field(..., description="Queue timestamp (ISO 8601)")
    timeout_at: str = Field(..., description="Timeout timestamp (ISO 8601)")


class FileStatusResponse(BaseModel):
    """File-specific status response (path provided)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path")
    exists: bool = Field(..., description="Whether file exists")
    hash: str | None = Field(..., description="File hash if exists")
    lock_state: str = Field(..., description="Lock state (unlocked, read_locked, write_locked)")
    queue_depth: int = Field(..., description="Request queue depth for this file")
    active_readers: int = Field(..., description="Number of active readers")
    pending_requests: list[PendingRequest] = Field(..., description="Pending requests for this file")


# Batch Response Models


class BatchSummary(BaseModel):
    """Summary of batch operation results."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(..., description="Total operations")
    succeeded: int = Field(..., description="Successful operations")
    failed: int = Field(..., description="Failed operations")
    contention: int = Field(default=0, description="Contention count (update only)")


class BatchReadResponse(BaseModel):
    """Response for async_batch_read tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    results: list[ReadSuccessResponse | ErrorResponse] = Field(..., description="Per-file results")
    summary: BatchSummary = Field(..., description="Batch summary")


class BatchWriteResponse(BaseModel):
    """Response for async_batch_write tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    results: list[WriteSuccessResponse | ErrorResponse] = Field(..., description="Per-file results")
    summary: BatchSummary = Field(..., description="Batch summary")


class BatchUpdateResponse(BaseModel):
    """Response for async_batch_update tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    results: list[UpdateSuccessResponse | ContentionResponse | ErrorResponse] = Field(..., description="Per-file results")
    summary: BatchSummary = Field(..., description="Batch summary")


# =============================================================================
# Shell extension response models
# =============================================================================


class ExecSuccessResponse(BaseModel):
    """Success response for foreground async_exec."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timestamp: str


class ExecDeniedResponse(BaseModel):
    """Denied response when a command matches a deny pattern."""

    model_config = ConfigDict(frozen=True)

    status: Literal["denied"] = "denied"
    command: str
    matched_pattern: str
    reason: str
    timestamp: str


class ExecBackgroundResponse(BaseModel):
    """Response for background async_exec."""

    model_config = ConfigDict(frozen=True)

    status: Literal["background"] = "background"
    task_id: str
    command: str
    timestamp: str


class WaitResponse(BaseModel):
    """Response for async_wait tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    waited_seconds: float
    reason: str
    task_result: dict | None = None
    timestamp: str


class SearchMatch(BaseModel):
    """A single search match."""

    model_config = ConfigDict(frozen=True)

    file: str
    line_number: int
    line_content: str
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Response for async_search tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    pattern: str
    matches: list[SearchMatch] = Field(default_factory=list)
    total_matches: int
    files_searched: int
    output_mode: str
    truncated: bool = False
    timestamp: str
