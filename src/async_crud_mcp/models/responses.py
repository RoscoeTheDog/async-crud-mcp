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
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TXN_NOT_FOUND = "TXN_NOT_FOUND"


# Shared Models


class RedactionEntry(BaseModel):
    """Metadata for a single redacted span in the content."""

    model_config = ConfigDict(frozen=True)

    id: int = Field(..., description="Sequential redaction ID (matches placeholder)")
    rule_name: str = Field(..., description="Content scan rule that matched")
    line: int = Field(..., description="1-based line number in the original content")
    col_start: int = Field(..., description="0-based start column in the line")
    original_length: int = Field(..., description="Character length of original content")


# Success Response Models


class ReadSuccessResponse(BaseModel):
    """Success response for async_read tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was read")
    content: str = Field(..., description="File content")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    total_lines: int = Field(..., description="Total number of lines in file")
    lines_returned: int = Field(..., description="Number of lines returned")
    redactions: list[RedactionEntry] | None = Field(
        default=None,
        description="Metadata for redacted spans in the content (when sensitive content was replaced with placeholders)"
    )


class WriteSuccessResponse(BaseModel):
    """Success response for async_write tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was written")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    bytes_written: int = Field(..., description="Number of bytes written")


class RegexAppliedMatch(BaseModel):
    """A single regex match that was successfully applied."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(..., description="Start offset in original content")
    end: int = Field(..., description="End offset in original content")
    line: int = Field(..., description="1-based line number")
    matched: str = Field(..., description="Text that was matched")
    replaced_with: str = Field(..., description="Replacement text")


class RegexBlockedMatch(BaseModel):
    """A single regex match that was blocked by content scanner."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(..., description="Start offset in original content")
    end: int = Field(..., description="End offset in original content")
    line: int = Field(..., description="1-based line number")
    error: str = Field(..., description="Reason the match was blocked")


class UpdateSuccessResponse(BaseModel):
    """Success response for async_update tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was updated")
    previous_hash: str = Field(..., description="Hash before update")
    hash: str = Field(..., description="Hash after update (format: sha256:...)")
    bytes_written: int = Field(..., description="Number of bytes written")
    regex_applied: list[RegexAppliedMatch] | None = Field(default=None, description="Regex matches that were applied")
    regex_blocked: list[RegexBlockedMatch] | None = Field(default=None, description="Regex matches blocked by content scanner")


class DeleteSuccessResponse(BaseModel):
    """Success response for async_delete tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was deleted")
    deleted_hash: str = Field(..., description="Hash of deleted file")
    recycled: bool = Field(default=False, description="True if file was moved to recycle bin (recoverable)")
    recycle_name: str | None = Field(default=None, description="Name in recycle bin (for restore)")


class RenameSuccessResponse(BaseModel):
    """Success response for async_rename tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    old_path: str = Field(..., description="Original file path")
    new_path: str = Field(..., description="New file path")
    hash: str = Field(..., description="File content hash (format: sha256:...)")
    cross_filesystem: bool = Field(default=False, description="Whether rename crossed filesystem boundaries")


class AppendSuccessResponse(BaseModel):
    """Success response for async_append tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was appended to")
    hash: str = Field(..., description="File content hash after append (format: sha256:...)")
    bytes_appended: int = Field(..., description="Number of bytes appended")
    total_size_bytes: int = Field(..., description="Total file size after append")


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


class MkdirSuccessResponse(BaseModel):
    """Success response for async_mkdir tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="Directory path that was created")
    created: bool = Field(..., description="True if directory was newly created, False if it already existed")


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


class JsonDiff(BaseModel):
    """JSON-formatted diff."""

    model_config = ConfigDict(frozen=True)

    format: Literal["json"] = "json"
    changes: list[DiffChange] = Field(..., description="List of changes")


class UnifiedDiff(BaseModel):
    """Unified diff format."""

    model_config = ConfigDict(frozen=True)

    format: Literal["unified"] = "unified"
    content: str = Field(..., description="Unified diff content")


class PatchConflict(BaseModel):
    """A patch that could not be applied."""

    model_config = ConfigDict(frozen=True)

    patch_index: int = Field(..., description="Index of conflicting patch")
    reason: str = Field(..., description="Reason patch could not be applied")


class ContentionResponse(BaseModel):
    """Contention response for update/delete/rename operations."""

    model_config = ConfigDict(frozen=True)

    status: Literal["contention"] = "contention"
    error_code: str = Field(default="HASH_MISMATCH", description="Error code for contention")
    path: str = Field(..., description="File path with contention")
    expected_hash: str = Field(..., description="Hash that was expected")
    current_hash: str = Field(..., description="Current file hash")
    modified_by: str = Field(
        default="unknown",
        description=(
            "Source of the modification that caused contention: "
            "'agent' if another MCP operation wrote the current content, "
            "'external' if modified outside MCP (user edit, git, etc.), "
            "'unknown' if no tracking data available"
        ),
    )
    message: str = Field(..., description="Human-readable contention message")
    diff: Annotated[JsonDiff | UnifiedDiff, Field(discriminator="format")] | None = Field(
        default=None, description="Diff showing changes (None when redacted due to sensitive content)"
    )
    redactions: list[RedactionEntry] | None = Field(
        default=None,
        description="Metadata for redacted spans in the diff (when sensitive content was replaced with placeholders)"
    )
    patches_applicable: bool | None = Field(default=None, description="Whether patches can still be applied (update only)")
    conflicts: list[PatchConflict] | None = Field(default=None, description="Conflicting patches (update only)")
    non_conflicting_patches: list[int] | None = Field(default=None, description="Indices of non-conflicting patches")


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
# Recycle bin response models
# =============================================================================


class RestoreSuccessResponse(BaseModel):
    """Success response for async_restore tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    restored_path: str = Field(..., description="Path where file was restored")
    original_path: str = Field(..., description="Original path before deletion")
    recycle_name: str = Field(..., description="Name in recycle bin")


class RecycleListEntry(BaseModel):
    """A single entry in the recycle bin listing."""

    model_config = ConfigDict(frozen=True)

    recycle_name: str = Field(..., description="Name in recycle bin")
    original_path: str = Field(..., description="Original file path")
    deleted_hash: str = Field(..., description="Hash at deletion time")
    timestamp: str = Field(..., description="Deletion timestamp (ISO 8601)")
    size_bytes: int = Field(..., description="File size in bytes")


class RecycleListResponse(BaseModel):
    """Response for recycle bin listing."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    entries: list[RecycleListEntry] = Field(..., description="Recycled file entries")
    recycle_dir: str = Field(..., description="Active recycle directory path")


class RecycleCleanResponse(BaseModel):
    """Response for recycle bin cleanup."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    removed_count: int = Field(..., description="Number of entries removed")
    retention_days: int = Field(..., description="Retention period used")


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
    timeout_applied: float | None = Field(default=None, description="Effective timeout when clamped from requested value")
    stdout_redactions: list[RedactionEntry] | None = Field(
        default=None,
        description="Metadata for redacted spans in stdout (when sensitive content was replaced with placeholders)"
    )
    stderr_redactions: list[RedactionEntry] | None = Field(
        default=None,
        description="Metadata for redacted spans in stderr (when sensitive content was replaced with placeholders)"
    )


class ExecDeniedResponse(BaseModel):
    """Denied response when a command matches a deny pattern."""

    model_config = ConfigDict(frozen=True)

    status: Literal["denied"] = "denied"
    command: str
    matched_pattern: str
    reason: str


class ExecBackgroundResponse(BaseModel):
    """Response for background async_exec."""

    model_config = ConfigDict(frozen=True)

    status: Literal["background"] = "background"
    task_id: str
    command: str


class TaskResultPayload(BaseModel):
    """Result payload from a completed background task."""

    model_config = ConfigDict(frozen=True)

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class TaskWaitResult(BaseModel):
    """Result for one task in a wait response."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    task_result: TaskResultPayload
    stdout_redactions: list[RedactionEntry] | None = None
    stderr_redactions: list[RedactionEntry] | None = None


class WaitResponse(BaseModel):
    """Response for async_wait tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    waited_seconds: float
    reason: str
    task_status: Literal["running", "completed", "all_running"] | None = None
    completed_tasks: list[TaskWaitResult] | None = None


class SearchMatch(BaseModel):
    """A single search match."""

    model_config = ConfigDict(frozen=True)

    file: str
    line_number: int
    line_content: str | None
    context_before: list[str | None] | None = Field(default=None)
    context_after: list[str | None] | None = Field(default=None)
    redactions: list[RedactionEntry] | None = Field(
        default=None,
        description="Metadata for redacted spans in the line (when sensitive content was replaced with placeholders)"
    )


class SearchResponse(BaseModel):
    """Response for async_search tool."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    matches: list[SearchMatch] = Field(default_factory=list)
    total_matches: int
    files_searched: int
    truncated: bool | None = Field(default=None, description="True if results were truncated by timeout")


# =============================================================================
# Transactional edit response models (ADR-001)
# =============================================================================


class StagedMatchEntry(BaseModel):
    """Preview of one staged match in a transaction."""

    model_config = ConfigDict(frozen=True)

    match_id: int = Field(..., description="Stable id for this match within the transaction")
    line: int = Field(..., description="1-based line number of the match")
    col_start: int = Field(..., description="0-based column offset of the match in its line")
    before: str = Field(..., description="Original matched text (redacted if sensitive)")
    after: str = Field(..., description="Proposed replacement (redacted if sensitive)")


class QueryReplaceResponse(BaseModel):
    """Response for async_query_replace: a staged transaction with a diff preview."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    txn_id: str = Field(..., description="Transaction id (pass to async_commit/async_amend/async_abort)")
    path: str = Field(..., description="File path being edited")
    base_hash: str = Field(..., description="File hash captured at query time (CAS token)")
    match_count: int = Field(..., description="Number of matches staged")
    matches: list[StagedMatchEntry] = Field(..., description="Per-match diff preview")
    redactions: list[RedactionEntry] | None = Field(
        default=None, description="Redaction metadata for sensitive spans in the preview"
    )


class CommitSuccessResponse(BaseModel):
    """Response for async_commit when the staged matches were applied."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    path: str = Field(..., description="File path that was updated")
    previous_hash: str = Field(..., description="Hash before commit")
    hash: str = Field(..., description="Hash after commit (format: sha256:...)")
    applied_count: int = Field(..., description="Number of matches applied")
    rebased: bool = Field(default=False, description="True if matches were relocated onto externally-changed content")


class StaleConflictResponse(BaseModel):
    """Response for async_commit when selected matches no longer validate (CAS failure)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["stale_conflict"] = "stale_conflict"
    txn_id: str = Field(..., description="The transaction id (still valid; re-query to refresh)")
    path: str = Field(..., description="File path with the conflict")
    base_hash: str = Field(..., description="Hash captured at query time")
    current_hash: str = Field(..., description="Current on-disk hash")
    stale_match_ids: list[int] = Field(..., description="Selected matches that no longer locate unambiguously")
    applicable_match_ids: list[int] = Field(..., description="Selected matches that still apply cleanly")
    message: str = Field(..., description="Human-readable conflict explanation")


class AmendResponse(BaseModel):
    """Response for async_amend."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    txn_id: str = Field(..., description="Transaction id")
    match_id: int = Field(..., description="Match id that was amended")


class AbortResponse(BaseModel):
    """Response for async_abort."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    txn_id: str = Field(..., description="Transaction id that was discarded")
    discarded: bool = Field(..., description="True if the transaction existed and was removed")
