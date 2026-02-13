"""Diff engine for computing differences between file contents.

This module provides two diff output formats:
1. JSON format: Structured change regions (added/removed/modified) with context
2. Unified format: Standard git-diff style output

Both formats include a DiffSummary with line counts and region counts.
Context lines are configurable (default from config.crud.diff_context_lines).
"""

import difflib
from typing import Literal

from async_crud_mcp.models.responses import (
    DiffChange,
    DiffSummary,
    JsonDiff,
    UnifiedDiff,
)


def compute_diff(
    old_content: str,
    new_content: str,
    diff_format: Literal["json", "unified"] = "json",
    context_lines: int = 3,
) -> JsonDiff | UnifiedDiff:
    """Compute differences between two file content strings.

    Args:
        old_content: Original content (expected)
        new_content: New content (current)
        diff_format: Output format - "json" (structured) or "unified" (git-diff style)
        context_lines: Number of context lines to include (default: 3)

    Returns:
        JsonDiff or UnifiedDiff model with changes and summary
    """
    if diff_format == "json":
        return compute_json_diff(old_content, new_content, context_lines)
    else:
        return compute_unified_diff(old_content, new_content, context_lines)


def compute_json_diff(
    old_content: str,
    new_content: str,
    context_lines: int = 3,
) -> JsonDiff:
    """Compute JSON-formatted diff with structured change regions.

    Uses difflib.SequenceMatcher to identify opcodes and map them to DiffChange objects.
    Each change includes type, location, content, and surrounding context.

    Args:
        old_content: Original content
        new_content: New content
        context_lines: Number of context lines before/after each change

    Returns:
        JsonDiff with list of changes and summary
    """
    old_lines = old_content.splitlines(keepends=False)
    new_lines = new_content.splitlines(keepends=False)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()

    changes: list[DiffChange] = []
    lines_added = 0
    lines_removed = 0
    lines_modified = 0

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue  # Skip equal sections

        # Extract context from adjacent equal blocks
        context_before = None
        context_after = None

        # Find previous equal block for context_before
        prev_idx = opcodes.index((tag, i1, i2, j1, j2)) - 1
        if prev_idx >= 0:
            prev_tag, prev_i1, prev_i2, _, _ = opcodes[prev_idx]
            if prev_tag == "equal":
                # Take last N lines from previous equal block
                ctx_start = max(prev_i1, prev_i2 - context_lines)
                if ctx_start < prev_i2:
                    context_before = "\n".join(old_lines[ctx_start:prev_i2])

        # Find next equal block for context_after
        next_idx = opcodes.index((tag, i1, i2, j1, j2)) + 1
        if next_idx < len(opcodes):
            next_tag, next_i1, next_i2, _, _ = opcodes[next_idx]
            if next_tag == "equal":
                # Take first N lines from next equal block
                ctx_end = min(next_i2, next_i1 + context_lines)
                if next_i1 < ctx_end:
                    context_after = "\n".join(old_lines[next_i1:ctx_end])

        if tag == "insert":
            # Lines added in new content
            change = DiffChange(
                type="added",
                start_line=j1 + 1,  # 1-indexed
                end_line=j2 if j2 > j1 + 1 else None,
                old_content=None,
                new_content="\n".join(new_lines[j1:j2]),
                context_before=context_before,
                context_after=context_after,
            )
            changes.append(change)
            lines_added += j2 - j1

        elif tag == "delete":
            # Lines removed from old content
            change = DiffChange(
                type="removed",
                start_line=i1 + 1,  # 1-indexed
                end_line=i2 if i2 > i1 + 1 else None,
                old_content="\n".join(old_lines[i1:i2]),
                new_content=None,
                context_before=context_before,
                context_after=context_after,
            )
            changes.append(change)
            lines_removed += i2 - i1

        elif tag == "replace":
            # Lines modified (replaced)
            change = DiffChange(
                type="modified",
                start_line=i1 + 1,  # 1-indexed (old line number)
                end_line=i2 if i2 > i1 + 1 else None,
                old_content="\n".join(old_lines[i1:i2]),
                new_content="\n".join(new_lines[j1:j2]),
                context_before=context_before,
                context_after=context_after,
            )
            changes.append(change)
            lines_modified += max(i2 - i1, j2 - j1)

    summary = DiffSummary(
        lines_added=lines_added,
        lines_removed=lines_removed,
        lines_modified=lines_modified,
        regions_changed=len(changes),
    )

    return JsonDiff(changes=changes, summary=summary)


def compute_unified_diff(
    old_content: str,
    new_content: str,
    context_lines: int = 3,
) -> UnifiedDiff:
    """Compute unified diff format (standard git-diff style).

    Uses difflib.unified_diff() to generate standard diff output.
    Parses the output to compute summary statistics.

    Args:
        old_content: Original content
        new_content: New content
        context_lines: Number of context lines (passed to unified_diff n parameter)

    Returns:
        UnifiedDiff with diff content and summary
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="expected",
            tofile="current",
            n=context_lines,
            lineterm="",
        )
    )

    diff_content = "\n".join(diff_lines)

    # Parse diff output to compute summary
    lines_added = 0
    lines_removed = 0
    regions_changed = 0

    for line in diff_lines:
        if line.startswith("@@"):
            regions_changed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_removed += 1

    # Lines modified = minimum of added and removed (represents replacements)
    lines_modified = min(lines_added, lines_removed)

    # Adjust pure adds/removes by subtracting modified
    lines_added -= lines_modified
    lines_removed -= lines_modified

    summary = DiffSummary(
        lines_added=lines_added,
        lines_removed=lines_removed,
        lines_modified=lines_modified,
        regions_changed=regions_changed,
    )

    return UnifiedDiff(content=diff_content, summary=summary)


def check_patch_applicability(
    current_content: str,
    patches: list[str],
) -> tuple[bool, list[int], list[int]]:
    """Check which patches from an update request can still apply to changed content.

    This helper is used in contention responses to determine if patches can be
    applied despite a hash mismatch.

    Args:
        current_content: Current file content
        patches: List of patch strings (unified diff format)

    Returns:
        Tuple of:
        - all_applicable: Whether all patches can be applied
        - applicable_indices: Indices of patches that can be applied
        - conflicting_indices: Indices of patches that cannot be applied
    """
    import subprocess
    import tempfile

    applicable_indices = []
    conflicting_indices = []

    for idx, patch in enumerate(patches):
        # Create temporary file with current content
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as tmp:
            tmp.write(current_content)
            tmp_path = tmp.name

        try:
            # Try to apply patch with --dry-run
            result = subprocess.run(
                ["patch", "--dry-run", tmp_path],
                input=patch,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                applicable_indices.append(idx)
            else:
                conflicting_indices.append(idx)

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # patch command not available or timeout - assume conflict
            conflicting_indices.append(idx)
        finally:
            # Clean up temp file
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    all_applicable = len(conflicting_indices) == 0

    return all_applicable, applicable_indices, conflicting_indices
