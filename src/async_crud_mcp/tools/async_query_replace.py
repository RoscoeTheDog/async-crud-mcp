"""Stage a transactional regex edit (query -> preview). See ADR-001.

Reads the file under a shared lock, runs the regex, and stages an EditTransaction
holding the matched spans + a content anchor for each, plus the file's base hash
(the CAS token). Returns a per-match diff preview (egress-scrubbed) but does NOT
mutate the file. The agent then commits a subset (async_commit), hand-edits a
replacement (async_amend), or discards it (async_abort).
"""

import os
import re
from typing import Union

from async_crud_mcp.core import (
    AccessDeniedError,
    ContentScanner,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    StagedMatch,
    TransactionManager,
    compute_hash,
    make_anchor,
)
from async_crud_mcp.models import (
    ErrorCode,
    ErrorResponse,
    QueryReplaceRequest,
    QueryReplaceResponse,
    RedactionEntry,
    StagedMatchEntry,
)


def _line_col(content: str, pos: int) -> tuple[int, int]:
    """Return (1-based line, 0-based column) for an offset in content."""
    line = content.count("\n", 0, pos) + 1
    col = pos - (content.rfind("\n", 0, pos) + 1)
    return line, col


async def async_query_replace(
    request: QueryReplaceRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    transaction_manager: TransactionManager,
    user_key: str,
    content_scanner: ContentScanner | None = None,
) -> Union[QueryReplaceResponse, ErrorResponse]:
    """Stage a transactional regex replace and return a diff preview."""
    try:
        try:
            validated = path_validator.validate_operation(request.path, "read")
        except AccessDeniedError as e:
            return ErrorResponse(error_code=ErrorCode.ACCESS_DENIED, message=str(e), path=request.path)
        except PathValidationError as e:
            return ErrorResponse(error_code=ErrorCode.PATH_OUTSIDE_BASE, message=str(e), path=request.path)

        if not os.path.exists(validated):
            return ErrorResponse(error_code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {request.path}", path=request.path)

        try:
            flags = re.IGNORECASE if request.case_insensitive else 0
            pattern = re.compile(request.pattern, flags)
        except re.error as e:
            return ErrorResponse(error_code=ErrorCode.INVALID_PATTERN, message=f"Invalid regex: {e}", path=request.path)

        try:
            rid = await lock_manager.acquire_read(str(validated), timeout=request.timeout)
        except LockTimeout:
            return ErrorResponse(error_code=ErrorCode.LOCK_TIMEOUT, message=f"Read lock timed out after {request.timeout}s", path=request.path)
        try:
            with open(validated, "rb") as f:
                raw = f.read()
            base_hash = compute_hash(raw)
            content = raw.decode("utf-8", errors="replace")
        finally:
            await lock_manager.release_read(str(validated), rid)

        # Build staged matches (replacement backreferences expanded per match).
        staged: list[StagedMatch] = []
        for i, m in enumerate(pattern.finditer(content), start=1):
            line, _col = _line_col(content, m.start())
            staged.append(StagedMatch(
                match_id=i, start=m.start(), end=m.end(), line=line,
                before=m.group(0), after=m.expand(request.replacement),
                anchor=make_anchor(content, m.start(), m.end()),
            ))

        txn = transaction_manager.create(
            path=str(validated), base_hash=base_hash, original_content=content,
            matches=staged, user_key=user_key, ttl=request.ttl,
        )

        # Diff preview with egress redaction of before/after (respects P1-8).
        entries: list[StagedMatchEntry] = []
        redactions: list[RedactionEntry] = []
        rid_counter = 0
        for m in staged:
            _line, col = _line_col(content, m.start)
            before_disp, after_disp = m.before, m.after
            if content_scanner is not None:
                rb = content_scanner.redact(m.before, path="<txn:before>")
                ra = content_scanner.redact(m.after, path="<txn:after>")
                before_disp, after_disp = rb.content, ra.content
                for r in list(rb.redactions) + list(ra.redactions):
                    rid_counter += 1
                    redactions.append(RedactionEntry(
                        id=rid_counter, rule_name=r.rule_name, line=m.line,
                        col_start=r.col_start, original_length=r.original_length,
                    ))
            entries.append(StagedMatchEntry(
                match_id=m.match_id, line=m.line, col_start=col,
                before=before_disp, after=after_disp,
            ))

        return QueryReplaceResponse(
            txn_id=txn.txn_id, path=str(validated), base_hash=base_hash,
            match_count=len(staged), matches=entries, redactions=redactions or None,
        )
    except Exception as e:
        return ErrorResponse(error_code=ErrorCode.SERVER_ERROR, message=f"Unexpected error during query_replace: {e}", path=request.path)
