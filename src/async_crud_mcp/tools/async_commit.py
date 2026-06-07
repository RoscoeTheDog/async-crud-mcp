"""Apply a staged transactional edit under optimistic CAS. See ADR-001.

Re-reads the file under a write lock and applies the selected staged matches:
  - Fast path: file unchanged since query (base_hash matches) -> apply by offset.
  - Rebase: file changed elsewhere -> relocate each selected match by its anchor;
    apply only if every selected match relocates unambiguously, else STALE_CONFLICT.
Write is atomic (temp+rename). The transaction is removed on success.
"""

import os
from typing import Union

from async_crud_mcp.core import (
    AccessDeniedError,
    ContentScanner,
    HashRegistry,
    LockManager,
    LockTimeout,
    PathValidationError,
    PathValidator,
    TransactionManager,
    apply_spans,
    atomic_write,
    compute_hash,
    rebase_match,
    spans_overlap,
)
from async_crud_mcp.models import (
    CommitRequest,
    CommitSuccessResponse,
    ErrorCode,
    ErrorResponse,
    StaleConflictResponse,
)


async def async_commit(
    request: CommitRequest,
    path_validator: PathValidator,
    lock_manager: LockManager,
    hash_registry: HashRegistry,
    transaction_manager: TransactionManager,
    user_key: str,
    content_scanner: ContentScanner | None = None,
) -> Union[CommitSuccessResponse, StaleConflictResponse, ErrorResponse]:
    """Apply selected staged matches to the file (CAS + rebase)."""
    try:
        txn = transaction_manager.get(request.txn_id, user_key)
        if txn is None:
            return ErrorResponse(error_code=ErrorCode.TXN_NOT_FOUND, message=f"Transaction not found or expired: {request.txn_id}")

        try:
            validated = path_validator.validate_operation(txn.path, "update")
        except AccessDeniedError as e:
            return ErrorResponse(error_code=ErrorCode.ACCESS_DENIED, message=str(e), path=txn.path)
        except PathValidationError as e:
            return ErrorResponse(error_code=ErrorCode.PATH_OUTSIDE_BASE, message=str(e), path=txn.path)
        path = str(validated)

        if request.match_ids is None:
            selected = list(txn.matches)
        else:
            wanted = set(request.match_ids)
            selected = [m for m in txn.matches if m.match_id in wanted]
        if not selected:
            return ErrorResponse(error_code=ErrorCode.VALIDATION_ERROR, message="No matching match_ids to commit", path=path)

        # Content-scan write guard (mirrors async_update's regex guard). A staged
        # match's `before` is the exact text the commit would overwrite -- the
        # rebase path also relocates by `before` -- so scanning it refuses to
        # clobber a secret the agent cannot see (reads are egress-redacted).
        # All-or-nothing: nothing is written and the transaction is preserved so
        # the caller can amend/deselect/abort.
        if content_scanner is not None:
            blocked = [m.match_id for m in selected if content_scanner.scan(m.before, path).blocked]
            if blocked:
                return ErrorResponse(
                    error_code=ErrorCode.CONTENT_BLOCKED,
                    message=(
                        f"Refusing to commit: {len(blocked)} selected match(es) {blocked} "
                        f"overlap egress-protected content; nothing was applied. Amend or "
                        f"deselect them, or abort the transaction."
                    ),
                    path=path,
                )

        try:
            rid = await lock_manager.acquire_write(path, timeout=request.timeout)
        except LockTimeout:
            return ErrorResponse(error_code=ErrorCode.LOCK_TIMEOUT, message=f"Write lock timed out after {request.timeout}s", path=path)

        try:
            if not os.path.exists(path):
                return ErrorResponse(error_code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}", path=path)
            with open(path, "rb") as f:
                raw = f.read()
            previous_hash = compute_hash(raw)
            current = raw.decode("utf-8", errors="replace")

            rebased = False
            if previous_hash == txn.base_hash:
                spans = [(m.start, m.end, m.after) for m in selected]
            else:
                rebased = True
                spans = []
                stale_ids: list[int] = []
                ok_ids: list[int] = []
                for m in selected:
                    loc = rebase_match(current, m)
                    if loc is None:
                        stale_ids.append(m.match_id)
                    else:
                        ok_ids.append(m.match_id)
                        spans.append((loc[0], loc[1], m.after))
                if stale_ids:
                    return StaleConflictResponse(
                        txn_id=txn.txn_id, path=path, base_hash=txn.base_hash,
                        current_hash=previous_hash, stale_match_ids=stale_ids,
                        applicable_match_ids=ok_ids,
                        message=(f"File changed since query; {len(stale_ids)} of {len(selected)} "
                                 f"selected matches no longer locate unambiguously. Re-query to refresh."),
                    )

            if spans_overlap([(s, e) for s, e, _ in spans]):
                return ErrorResponse(error_code=ErrorCode.VALIDATION_ERROR, message="Selected matches overlap; cannot apply together", path=path)

            new_bytes = apply_spans(current, spans).encode("utf-8")
            atomic_write(path, new_bytes)
            new_hash = compute_hash(new_bytes)
            hash_registry.update(path, new_hash)
        finally:
            await lock_manager.release_write(path, rid)

        transaction_manager.remove(txn.txn_id)
        return CommitSuccessResponse(
            path=path, previous_hash=previous_hash, hash=new_hash,
            applied_count=len(spans), rebased=rebased,
        )
    except Exception as e:
        return ErrorResponse(error_code=ErrorCode.SERVER_ERROR, message=f"Unexpected error during commit: {e}")
