"""File content search tool for MCP operations.

Searches files by regex pattern with glob filtering, respecting PathValidator
and ContentScanner rules.
"""

import os
import re
import time
from collections import defaultdict
from pathlib import Path

from async_crud_mcp.config import SearchConfig
from async_crud_mcp.core import ContentScanner, PathValidator
from async_crud_mcp.models.requests import SearchRequest
from async_crud_mcp.models.responses import (
    ErrorCode,
    ErrorResponse,
    RedactionEntry,
    SearchMatch,
    SearchResponse,
)


async def async_search(
    request: SearchRequest,
    search_config: SearchConfig,
    path_validator: PathValidator,
    content_scanner: ContentScanner | None = None,
    project_root: Path | None = None,
) -> SearchResponse | ErrorResponse:
    """Search file contents by regex pattern.

    Args:
        request: Search request with pattern, path, glob, etc.
        search_config: Search configuration (enabled, max_results, etc.).
        path_validator: For validating file access.
        content_scanner: Optional content scanner for sensitive file filtering.
        project_root: Active project root for path resolution.

    Returns:
        SearchResponse or ErrorResponse.
    """
    # 1. Check search enabled
    if not search_config.enabled:
        return ErrorResponse(
            error_code=ErrorCode.SEARCH_DISABLED,
            message="Search is disabled in configuration.",
        )

    # 2. Reject empty pattern
    if not request.pattern:
        return ErrorResponse(
            error_code=ErrorCode.INVALID_PATTERN,
            message="Search pattern cannot be empty.",
        )

    # 3. Compile regex
    flags = re.IGNORECASE if request.case_insensitive else 0
    try:
        pattern = re.compile(request.pattern, flags)
    except re.error as e:
        return ErrorResponse(
            error_code=ErrorCode.INVALID_PATTERN,
            message=f"Invalid regex pattern: {e}",
        )

    # 3. Resolve search path
    if request.path:
        search_path = Path(request.path)
    elif project_root:
        search_path = project_root
    else:
        return ErrorResponse(
            error_code=ErrorCode.SERVER_ERROR,
            message="No search path specified and no project activated.",
        )

    # Validate search path is within project root (os.sep prevents /project-foo matching /project)
    if project_root:
        resolved_root = str(project_root.resolve())
        resolved_search = str(search_path.resolve())
        root_with_sep = resolved_root if resolved_root.endswith(os.sep) else resolved_root + os.sep
        if resolved_search != resolved_root and not resolved_search.startswith(root_with_sep):
            return ErrorResponse(
                error_code=ErrorCode.PATH_OUTSIDE_BASE,
                message=f"Search path is outside project root: {search_path}",
            )

    if not search_path.is_dir():
        return ErrorResponse(
            error_code=ErrorCode.DIR_NOT_FOUND,
            message=f"Search path is not a directory: {search_path}",
        )

    # 4. Clamp max_results
    max_results = min(request.max_results, search_config.max_results)

    # 5. Collect files, excluding configured directories
    exclude_dirs = set(search_config.exclude_dirs)
    glob_pattern = request.glob

    def _is_excluded(p: Path) -> bool:
        """Check if any path component matches an excluded directory name."""
        return bool(exclude_dirs.intersection(p.parts))

    if request.recursive:
        files = [f for f in search_path.rglob(glob_pattern) if f.is_file() and not _is_excluded(f.relative_to(search_path))]
    else:
        files = [f for f in search_path.glob(glob_pattern) if f.is_file() and not _is_excluded(f.relative_to(search_path))]

    # 6. Search files
    matches: list[SearchMatch] = []
    files_searched = 0
    file_match_counts: dict[str, int] = defaultdict(int)
    total_matches = 0

    for file_path in sorted(files):
        # Validate access
        try:
            path_validator.validate_operation(str(file_path), "read")
        except Exception:
            continue

        # Check file size
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > search_config.max_file_size_bytes:
            continue

        # Read file
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        # Content scanner: build set of redacted line numbers (1-based)
        redacted_lines: dict[int, str] = {}  # line_number -> rule_name
        redacted_result = None
        if content_scanner is not None:
            redacted_result = content_scanner.redact(content, str(file_path))
            if redacted_result.has_redactions:
                for span in redacted_result.redactions:
                    if span.line not in redacted_lines:
                        redacted_lines[span.line] = span.rule_name

        files_searched += 1
        lines = content.splitlines()

        for line_idx, line in enumerate(lines):
            if pattern.search(line):
                total_matches += 1
                file_match_counts[str(file_path)] += 1

                if request.output_mode == "count":
                    continue
                if request.output_mode == "files_with_matches":
                    # Only record one match per file
                    if file_match_counts[str(file_path)] > 1:
                        continue

                if len(matches) >= max_results:
                    continue

                line_num = line_idx + 1  # 1-based

                # Build context
                ctx_before: list[str | None] = []
                ctx_after: list[str | None] = []
                if request.context_lines > 0:
                    start = max(0, line_idx - request.context_lines)
                    ctx_before = [
                        None if (start + i + 1) in redacted_lines else lines[start + i]
                        for i in range(line_idx - start)
                    ]
                    end = min(len(lines), line_idx + 1 + request.context_lines)
                    ctx_after = [
                        None if (line_idx + 1 + j + 1) in redacted_lines else lines[line_idx + 1 + j]
                        for j in range(end - line_idx - 1)
                    ]

                is_redacted = line_num in redacted_lines
                # Build per-line RedactionEntry from spans overlapping this line
                line_redaction_entries: list[RedactionEntry] | None = None
                if is_redacted and redacted_result is not None:
                    line_redaction_entries = [
                        RedactionEntry(
                            id=span.id,
                            rule_name=span.rule_name,
                            line=span.line,
                            col_start=span.col_start,
                            original_length=span.original_length,
                        )
                        for span in redacted_result.redactions
                        if span.line == line_num
                    ]
                matches.append(SearchMatch(
                    file=str(file_path),
                    line_number=line_num,
                    line_content=None if is_redacted else line,
                    context_before=ctx_before,
                    context_after=ctx_after,
                    redactions=line_redaction_entries,
                ))

    return SearchResponse(
        matches=matches,
        total_matches=total_matches,
        files_searched=files_searched,
    )
