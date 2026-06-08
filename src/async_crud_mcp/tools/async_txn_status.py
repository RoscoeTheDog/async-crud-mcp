"""Read-only inspection of an open transaction (ADR-001 / F9).

Relocates each currently-staged match against the LIVE file via the same
rebase logic async_commit uses, and returns a redacted, current-position
preview plus per-match locatability (which predicts whether commit would
apply or report it stale) and the transaction's remaining TTL.

Invariants:
  - Never re-scans the file for the pattern -- the found set stays frozen; this
    only relocates the matches already staged (occurrences introduced by earlier
    replacements are intentionally NOT surfaced).
  - Never writes and never holds a write lock; a brief read lock only.
  - Positions are OPTIMISTIC: they reflect the file at this instant. An external
    write afterwards invalidates them; only async_commit's CAS is authoritative.
"""

import os
from typing import Union

from async_crud_mcp.core import (
    AccessDeniedError,
    ContentScanner,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    TransactionManager,
    compute_hash,
    rebase_match,
)
from async_crud_mcp.models import (
    ErrorCode,
    ErrorResponse,
    RedactionEntry,
    TxnStatusMatchEntry,
    TxnStatusRequest,
    TxnStatusResponse,
)


def _line_col(content: str, pos: int) -> tuple[int, int]:
    """Return (1-based line, 0-based column) for an offset in content."""
    line = content.count("\n", 0, pos) + 1
    col = pos - (content.rfind("\n", 0, pos) + 1)
    return line, col


async def async_txn_status(
    request: TxnStatusRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    transaction_manager: TransactionManager,
    user_key: str,
    content_scanner: ContentScanner | None = None,
) -> Union[TxnStatusResponse, ErrorResponse]:
    """Report the live state of an open transaction without mutating it."""
    try:
        txn = transaction_manager.get(request.txn_id, user_key)
        if txn is None:
            return ErrorResponse(error_code=ErrorCode.TXN_NOT_FOUND, message=f"Transaction not found or expired: {request.txn_id}")

        try:
            validated = path_validator.validate_operation(txn.path, "read")
        except AccessDeniedError as e:
            return ErrorResponse(error_code=ErrorCode.ACCESS_DENIED, message=str(e), path=txn.path)
        except PathValidationError as e:
            return ErrorResponse(error_code=ErrorCode.PATH_OUTSIDE_BASE, message=str(e), path=txn.path)
        path = str(validated)

        if not os.path.exists(path):
            return ErrorResponse(error_code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}", path=path)

        try:
            rid = await lock_manager.acquire_read(path, timeout=request.timeout)
        except LockTimeout:
            return ErrorResponse(error_code=ErrorCode.LOCK_TIMEOUT, message=f"Read lock timed out after {request.timeout}s", path=path)
        try:
            with open(path, "rb") as f:
                raw = f.read()
            current_hash = compute_hash(raw)
            current = raw.decode("utf-8", errors="replace")
        finally:
            await lock_manager.release_read(path, rid)

        file_changed = current_hash != txn.base_hash

        entries: list[TxnStatusMatchEntry] = []
        redactions: list[RedactionEntry] = []
        locatable_ids: list[int] = []
        stale_ids: list[int] = []
        rid_counter = 0
        for m in txn.matches:
            # Mirror async_commit's location logic so locatability predicts the
            # commit outcome: fast path (file unchanged) uses the stored offsets;
            # otherwise relocate by content anchor (ambiguous/gone -> stale).
            if not file_changed and current[m.start:m.end] == m.before:
                loc: tuple[int, int] | None = (m.start, m.end)
            else:
                loc = rebase_match(current, m)

            cur_line = cur_col = None
            if loc is not None:
                locatable_ids.append(m.match_id)
                cur_line, cur_col = _line_col(current, loc[0])
            else:
                stale_ids.append(m.match_id)

            before_disp, after_disp = m.before, m.after
            if content_scanner is not None:
                rb = content_scanner.redact(m.before, path="<txn:before>")
                ra = content_scanner.redact(m.after, path="<txn:after>")
                before_disp, after_disp = rb.content, ra.content
                for r in list(rb.redactions) + list(ra.redactions):
                    rid_counter += 1
                    redactions.append(RedactionEntry(
                        id=rid_counter, rule_name=r.rule_name,
                        line=cur_line if cur_line is not None else 0,
                        col_start=r.col_start, original_length=r.original_length,
                    ))

            entries.append(TxnStatusMatchEntry(
                match_id=m.match_id, locatable=loc is not None,
                line=cur_line, col_start=cur_col,
                before=before_disp, after=after_disp,
            ))

        return TxnStatusResponse(
            txn_id=txn.txn_id, path=path, base_hash=txn.base_hash,
            current_hash=current_hash, file_changed=file_changed,
            match_count=len(txn.matches), matches=entries,
            locatable_match_ids=locatable_ids, stale_match_ids=stale_ids,
            ttl_remaining=txn.ttl_remaining, redactions=redactions or None,
        )
    except Exception as e:
        return ErrorResponse(error_code=ErrorCode.SERVER_ERROR, message=f"Unexpected error during txn_status: {e}")
