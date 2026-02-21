"""Request models for async-crud-mcp MCP tools.

All request models use Pydantic v2 BaseModel with strict field typing.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Patch(BaseModel):
    """A patch operation for file content updates."""

    old_string: str = Field(..., description="The string to replace")
    new_string: str = Field(..., description="The replacement string")


class AsyncReadRequest(BaseModel):
    """Request model for async_read tool."""

    path: str = Field(..., description="File path to read")
    offset: int = Field(default=0, description="Line offset to start reading from")
    limit: int | None = Field(default=None, description="Maximum number of lines to read")
    encoding: str = Field(default="utf-8", description="File encoding")


class AsyncWriteRequest(BaseModel):
    """Request model for async_write tool."""

    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")
    encoding: str = Field(default="utf-8", description="File encoding")
    create_dirs: bool = Field(default=True, description="Create parent directories if missing")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")


class AsyncUpdateRequest(BaseModel):
    """Request model for async_update tool."""

    path: str = Field(..., description="File path to update")
    expected_hash: str = Field(..., description="Expected file hash for conflict detection")
    content: str | None = Field(default=None, description="New file content (mutually exclusive with patches)")
    patches: list[Patch] | None = Field(default=None, description="List of patches to apply (mutually exclusive with content)")
    encoding: str = Field(default="utf-8", description="File encoding")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")
    diff_format: Literal["json", "unified"] = Field(default="json", description="Diff format for contention responses")

    @model_validator(mode="after")
    def validate_content_or_patches(self) -> "AsyncUpdateRequest":
        """Validate that exactly one of content or patches is provided."""
        has_content = self.content is not None
        has_patches = self.patches is not None

        if has_content and has_patches:
            raise ValueError("Exactly one of content or patches must be provided")
        if not has_content and not has_patches:
            raise ValueError("Exactly one of content or patches must be provided")

        return self


class AsyncDeleteRequest(BaseModel):
    """Request model for async_delete tool."""

    path: str = Field(..., description="File path to delete")
    expected_hash: str | None = Field(default=None, description="Expected file hash for conflict detection")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")
    diff_format: Literal["json", "unified"] = Field(default="json", description="Diff format for contention responses")


class AsyncRenameRequest(BaseModel):
    """Request model for async_rename tool."""

    old_path: str = Field(..., description="Current file path")
    new_path: str = Field(..., description="New file path")
    expected_hash: str | None = Field(default=None, description="Expected file hash for conflict detection")
    overwrite: bool = Field(default=False, description="Overwrite destination if it exists")
    create_dirs: bool = Field(default=True, description="Create parent directories if missing")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")
    diff_format: Literal["json", "unified"] = Field(default="json", description="Diff format for contention responses")


class AsyncAppendRequest(BaseModel):
    """Request model for async_append tool."""

    path: str = Field(..., description="File path to append to")
    content: str = Field(..., description="Content to append")
    encoding: str = Field(default="utf-8", description="File encoding")
    create_if_missing: bool = Field(default=False, description="Create file if it does not exist")
    create_dirs: bool = Field(default=True, description="Create parent directories if missing")
    separator: str = Field(default="", description="Separator to insert before content")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")


class AsyncListRequest(BaseModel):
    """Request model for async_list tool."""

    path: str = Field(..., description="Directory path to list")
    pattern: str = Field(default="*", description="Glob pattern to filter entries")
    recursive: bool = Field(default=False, description="Recursively list subdirectories")
    include_hashes: bool = Field(default=False, description="Include file hashes in response")


class AsyncStatusRequest(BaseModel):
    """Request model for async_status tool."""

    path: str | None = Field(default=None, description="Optional file path for file-specific status")


class BatchReadItem(BaseModel):
    """A single file read operation in a batch request."""

    path: str = Field(..., description="File path to read")
    offset: int = Field(default=0, description="Line offset to start reading from")
    limit: int | None = Field(default=None, description="Maximum number of lines to read")
    encoding: str = Field(default="utf-8", description="File encoding")


class BatchWriteItem(BaseModel):
    """A single file write operation in a batch request."""

    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")
    encoding: str = Field(default="utf-8", description="File encoding")
    create_dirs: bool = Field(default=True, description="Create parent directories if missing")


class BatchUpdateItem(BaseModel):
    """A single file update operation in a batch request."""

    path: str = Field(..., description="File path to update")
    expected_hash: str = Field(..., description="Expected file hash for conflict detection")
    content: str | None = Field(default=None, description="New file content (mutually exclusive with patches)")
    patches: list[Patch] | None = Field(default=None, description="List of patches to apply (mutually exclusive with content)")
    encoding: str = Field(default="utf-8", description="File encoding")

    @model_validator(mode="after")
    def validate_content_or_patches(self) -> "BatchUpdateItem":
        """Validate that exactly one of content or patches is provided."""
        has_content = self.content is not None
        has_patches = self.patches is not None

        if has_content and has_patches:
            raise ValueError("Exactly one of content or patches must be provided")
        if not has_content and not has_patches:
            raise ValueError("Exactly one of content or patches must be provided")

        return self


class AsyncBatchReadRequest(BaseModel):
    """Request model for async_batch_read tool."""

    files: list[BatchReadItem] = Field(..., description="List of files to read")


class AsyncBatchWriteRequest(BaseModel):
    """Request model for async_batch_write tool."""

    files: list[BatchWriteItem] = Field(..., description="List of files to write")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")


class AsyncBatchUpdateRequest(BaseModel):
    """Request model for async_batch_update tool."""

    files: list[BatchUpdateItem] = Field(..., description="List of files to update")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")
    diff_format: Literal["json", "unified"] = Field(default="json", description="Diff format for contention responses")


# =============================================================================
# Shell extension request models
# =============================================================================


class ExecRequest(BaseModel):
    """Request model for async_exec tool."""

    command: str = Field(..., description="Shell command to execute")
    timeout: float = Field(default=30.0, description="Command timeout in seconds")
    cwd: str | None = Field(default=None, description="Working directory (default: project root)")
    env: dict[str, str] | None = Field(default=None, description="Additional environment variables")
    background: bool = Field(default=False, description="Run command in background")


class WaitRequest(BaseModel):
    """Request model for async_wait tool."""

    seconds: float = Field(default=0.0, ge=0, description="Seconds to sleep (when no task_id)")
    task_id: str | None = Field(default=None, description="Background task ID to wait for")


class SearchRequest(BaseModel):
    """Request model for async_search tool."""

    pattern: str = Field(..., description="Regex pattern to search for")
    path: str | None = Field(default=None, description="Search path (default: project root)")
    glob: str = Field(default="*", description="Glob pattern to filter files")
    recursive: bool = Field(default=True, description="Search subdirectories")
    case_insensitive: bool = Field(default=False, description="Case-insensitive matching")
    max_results: int = Field(default=100, ge=1, description="Maximum matches to return")
    context_lines: int = Field(default=0, ge=0, le=10, description="Context lines before/after match")
    output_mode: Literal["content", "files_with_matches", "count"] = Field(
        default="content", description="Output mode"
    )
