"""Transactional edit engine: staged query -> preview -> commit with optimistic
concurrency control (compare-and-swap).

See .claude/implementation/adr-001-transactional-edit-engine.md.

A query_replace stages an EditTransaction (UUID) holding the matched spans plus a
content anchor for each, and the file's base hash. commit re-reads the file and
applies the selected matches atomically only if they still validate (CAS):

  - Fast path: file unchanged since query (base_hash matches) -> apply by offset.
  - Rebase path: file changed elsewhere -> relocate each selected match by its
    content anchor; apply only if EVERY selected match relocates unambiguously,
    otherwise report the stale ones (the caller returns STALE_CONFLICT).

Pessimistic locks are taken only for the brief commit critical section (by the
calling tool), never across the agent's think-time. Transactions are partitioned
by user_key and expire via TTL.
"""

import time
import uuid
from dataclasses import dataclass


# Characters of surrounding context (each side) captured to anchor a match so it
# can be relocated if the file changed elsewhere between query and commit.
_ANCHOR_WINDOW = 48


def make_anchor(content: str, start: int, end: int, window: int = _ANCHOR_WINDOW) -> str:
    """Return a context-anchored signature for the span [start, end).

    The anchor is the matched text plus up to `window` characters of surrounding
    context, used to relocate the span during rebase.
    """
    lo = max(0, start - window)
    hi = min(len(content), end + window)
    return content[lo:hi]


def _find_all(haystack: str, needle: str) -> list[int]:
    """Return all start offsets of `needle` in `haystack` (non-overlapping scan)."""
    if not needle:
        return []
    out: list[int] = []
    i = haystack.find(needle)
    while i != -1:
        out.append(i)
        i = haystack.find(needle, i + 1)
    return out


@dataclass
class StagedMatch:
    """A single staged replacement within a transaction."""

    match_id: int
    start: int       # offset in the ORIGINAL content
    end: int         # exclusive offset in the ORIGINAL content
    line: int        # 1-based line number of the match start
    before: str      # original matched text
    after: str       # replacement text (mutable via amend)
    anchor: str      # context-anchored signature for rebase


@dataclass
class EditTransaction:
    """A staged transactional edit over a single file."""

    txn_id: str
    path: str
    base_hash: str
    original_content: str
    matches: list[StagedMatch]
    user_key: str
    created_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl


def rebase_match(current_content: str, match: StagedMatch) -> tuple[int, int] | None:
    """Relocate a staged match in possibly-changed content via its anchor.

    Returns (start, end) of the match's `before` text in `current_content` if it
    can be located UNAMBIGUOUSLY, else None (stale / ambiguous / gone). Conservative
    by design: any ambiguity is treated as stale so a commit never clobbers.
    """
    # Primary: the context-anchored window appears exactly once.
    occ = _find_all(current_content, match.anchor)
    if len(occ) == 1:
        rel = match.anchor.find(match.before)
        if rel != -1:
            start = occ[0] + rel
            return (start, start + len(match.before))
    # Fallback: the exact matched text appears exactly once.
    occ_b = _find_all(current_content, match.before)
    if len(occ_b) == 1:
        return (occ_b[0], occ_b[0] + len(match.before))
    return None


def apply_spans(content: str, spans: list[tuple[int, int, str]]) -> str:
    """Apply (start, end, replacement) spans to `content`.

    Spans must be non-overlapping. Applied in reverse start order so earlier
    offsets stay valid during replacement.
    """
    for start, end, after in sorted(spans, key=lambda s: s[0], reverse=True):
        content = content[:start] + after + content[end:]
    return content


def spans_overlap(spans: list[tuple[int, int]]) -> bool:
    """Return True if any two [start, end) spans overlap."""
    ordered = sorted(spans, key=lambda s: s[0])
    for prev, cur in zip(ordered, ordered[1:]):
        if cur[0] < prev[1]:
            return True
    return False


class TransactionManager:
    """In-memory store of staged edit transactions with TTL-based GC.

    Transactions are partitioned by `user_key`: a txn_id created by one user is
    invisible to another. Expired transactions are pruned lazily on access and
    via prune_expired() (call from a background sweep).
    """

    def __init__(self, default_ttl: float = 600.0):
        self._default_ttl = default_ttl
        self._txns: dict[str, EditTransaction] = {}

    def create(
        self,
        path: str,
        base_hash: str,
        original_content: str,
        matches: list[StagedMatch],
        user_key: str,
        ttl: float | None = None,
    ) -> EditTransaction:
        txn = EditTransaction(
            txn_id=uuid.uuid4().hex,
            path=path,
            base_hash=base_hash,
            original_content=original_content,
            matches=matches,
            user_key=user_key,
            created_at=time.monotonic(),
            ttl=ttl if ttl is not None else self._default_ttl,
        )
        self._txns[txn.txn_id] = txn
        return txn

    def get(self, txn_id: str, user_key: str) -> EditTransaction | None:
        """Return the transaction if it exists, is unexpired, and belongs to user_key."""
        txn = self._txns.get(txn_id)
        if txn is None:
            return None
        if txn.expired:
            self._txns.pop(txn_id, None)
            return None
        if txn.user_key != user_key:
            return None
        return txn

    def remove(self, txn_id: str) -> bool:
        return self._txns.pop(txn_id, None) is not None

    def amend(self, txn_id: str, user_key: str, match_id: int, new_after: str) -> StagedMatch | None:
        """Override the staged replacement for one match; returns it, or None."""
        txn = self.get(txn_id, user_key)
        if txn is None:
            return None
        for m in txn.matches:
            if m.match_id == match_id:
                m.after = new_after
                return m
        return None

    def prune_expired(self) -> int:
        """Drop all expired transactions; returns the count removed."""
        stale = [tid for tid, t in self._txns.items() if t.expired]
        for tid in stale:
            self._txns.pop(tid, None)
        return len(stale)

    @property
    def count(self) -> int:
        return len(self._txns)
