"""Integration tests for the transactional edit tools (ADR-001).

Covers async_query_replace -> async_commit/async_amend/async_abort: preview,
subset commit, backreferences, amend, optimistic CAS (stale-conflict + rebase),
cross-user isolation, and preview redaction.
"""

import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.config import _default_content_scan_rules
from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, TransactionManager, compute_hash
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.models import (
    AbortRequest,
    AmendRequest,
    CommitRequest,
    ErrorCode,
    QueryReplaceRequest,
    TxnStatusRequest,
)
from async_crud_mcp.tools import (
    async_abort,
    async_amend,
    async_commit,
    async_query_replace,
    async_txn_status,
)

USER = "test-user"


@pytest.fixture
def base_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def pv(base_dir):
    return PathValidator(base_directories=[str(base_dir)])


@pytest.fixture
def lm():
    return LockManager()


@pytest.fixture
def hr():
    return HashRegistry()


@pytest.fixture
def tm():
    return TransactionManager()


def write(p: Path, content: str) -> str:
    b = content.encode("utf-8")
    p.write_bytes(b)
    return compute_hash(b)


@pytest.mark.asyncio
async def test_query_then_commit_all(base_dir, pv, lm, hr, tm):
    f = base_dir / "a.txt"
    write(f, "foo bar foo baz foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, USER)
    assert q.status == "ok" and q.match_count == 3
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "ok" and c.applied_count == 3 and c.rebased is False
    assert f.read_text() == "X bar X baz X"
    # transaction is consumed on commit
    c2 = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c2.status == "error" and c2.error_code == ErrorCode.TXN_NOT_FOUND


@pytest.mark.asyncio
async def test_commit_subset(base_dir, pv, lm, hr, tm):
    f = base_dir / "b.txt"
    write(f, "foo foo foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, USER)
    c = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2]), pv, lm, hr, tm, USER)
    assert c.status == "ok" and c.applied_count == 1
    assert f.read_text() == "foo X foo"


@pytest.mark.asyncio
async def test_subset_commit_keeps_txn_open(base_dir, pv, lm, hr, tm):
    # A subset commit retains the unapplied matches; they commit on the SAME txn,
    # relocated via rebase (each `before` is unique here so it locates cleanly).
    f = base_dir / "m.txt"
    write(f, "func_alpha()\nfunc_beta()\nfunc_gamma()\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"func_(\w+)\(\)", replacement=r"method_\1()"),
        pv, lm, tm, USER,
    )
    assert q.match_count == 3
    c1 = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2]), pv, lm, hr, tm, USER)
    assert c1.status == "ok" and c1.applied_count == 1
    assert c1.txn_id == q.txn_id and c1.remaining_match_ids == [1, 3]
    assert f.read_text() == "func_alpha()\nmethod_beta()\nfunc_gamma()\n"
    # remaining matches commit on the same txn (file changed -> rebase path)
    c2 = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[1, 3]), pv, lm, hr, tm, USER)
    assert c2.status == "ok" and c2.applied_count == 2 and c2.rebased is True
    assert f.read_text() == "method_alpha()\nmethod_beta()\nmethod_gamma()\n"
    # exhausted -> txn consumed
    c3 = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c3.status == "error" and c3.error_code == ErrorCode.TXN_NOT_FOUND


@pytest.mark.asyncio
async def test_full_commit_consumes_txn(base_dir, pv, lm, hr, tm):
    # A commit that applies every staged match leaves nothing open.
    f = base_dir / "m2.txt"
    write(f, "foo foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, USER)
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "ok" and c.applied_count == 2
    assert c.txn_id is None and c.remaining_match_ids is None
    assert tm.count == 0


@pytest.mark.asyncio
async def test_zero_match_creates_no_txn(base_dir, pv, lm, tm):
    # An empty match set must not allocate a transaction (nothing to commit).
    f = base_dir / "n.txt"
    write(f, "nothing to see here")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="ZZZ_NOPE", replacement="x"), pv, lm, tm, USER)
    assert q.status == "ok" and q.match_count == 0 and q.txn_id is None
    assert tm.count == 0


@pytest.mark.asyncio
async def test_amend_then_commit(base_dir, pv, lm, hr, tm):
    f = base_dir / "c.txt"
    write(f, "hello world")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="world", replacement="planet"), pv, lm, tm, USER)
    a = await async_amend(AmendRequest(txn_id=q.txn_id, match_id=1, replacement="galaxy"), tm, USER)
    assert a.status == "ok"
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "ok"
    assert f.read_text() == "hello galaxy"


@pytest.mark.asyncio
async def test_backreference_replacement(base_dir, pv, lm, hr, tm):
    f = base_dir / "d.txt"
    write(f, "def alpha( def beta(")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"def (\w+)\(", replacement=r"def new_\1("), pv, lm, tm, USER)
    assert q.match_count == 2
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "ok"
    assert f.read_text() == "def new_alpha( def new_beta("


@pytest.mark.asyncio
async def test_stale_conflict_on_ambiguous_change(base_dir, pv, lm, hr, tm):
    f = base_dir / "e.txt"
    write(f, "uniquePrefix TARGET uniqueSuffix")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="TARGET", replacement="DONE"), pv, lm, tm, USER)
    # external rewrite: anchor no longer locates and TARGET becomes ambiguous
    write(f, "TARGET TARGET TARGET")
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "stale_conflict" and c.stale_match_ids == [1]
    assert f.read_text() == "TARGET TARGET TARGET"  # file untouched on conflict


@pytest.mark.asyncio
async def test_rebase_on_faraway_change(base_dir, pv, lm, hr, tm):
    f = base_dir / "g.txt"
    pad = "x" * 100
    write(f, pad + " UNIQUE_TARGET " + pad)
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="UNIQUE_TARGET", replacement="REPLACED"), pv, lm, tm, USER)
    # external change far away (prepend) -> anchor still unique -> rebase applies
    write(f, "PREPEND\n" + pad + " UNIQUE_TARGET " + pad)
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "ok" and c.rebased is True
    text = f.read_text()
    assert "REPLACED" in text and "UNIQUE_TARGET" not in text


@pytest.mark.asyncio
async def test_abort_is_idempotent(base_dir, pv, lm, hr, tm):
    f = base_dir / "h.txt"
    write(f, "foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, USER)
    ab = await async_abort(AbortRequest(txn_id=q.txn_id), tm, USER)
    assert ab.status == "ok" and ab.discarded is True
    ab2 = await async_abort(AbortRequest(txn_id=q.txn_id), tm, USER)
    assert ab2.discarded is False
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER)
    assert c.status == "error" and c.error_code == ErrorCode.TXN_NOT_FOUND


@pytest.mark.asyncio
async def test_cross_user_isolation(base_dir, pv, lm, hr, tm):
    f = base_dir / "i.txt"
    write(f, "foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, "userA")
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, "userB")
    assert c.status == "error" and c.error_code == ErrorCode.TXN_NOT_FOUND
    assert f.read_text() == "foo"  # untouched


@pytest.mark.asyncio
async def test_commit_unknown_txn(base_dir, pv, lm, hr, tm):
    c = await async_commit(CommitRequest(txn_id="deadbeef"), pv, lm, hr, tm, USER)
    assert c.status == "error" and c.error_code == ErrorCode.TXN_NOT_FOUND


@pytest.mark.asyncio
async def test_commit_blocks_secret_match(base_dir, pv, lm, hr, tm):
    # The transactional commit must refuse to overwrite a region whose original
    # text is egress-protected (parity with async_update's regex write guard).
    scanner = ContentScanner(rules=_default_content_scan_rules(), enabled=True)
    f = base_dir / "k.txt"
    original = 'keep\napi_key = "sk-test-SECRETVALUE0000000000000000"\nkeep\n'
    write(f, original)
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r'api_key = "[^"]*"', replacement='api_key = "ROTATED"'),
        pv, lm, tm, USER, content_scanner=scanner,
    )
    assert q.status == "ok" and q.match_count == 1
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER, content_scanner=scanner)
    assert c.status == "error" and c.error_code == ErrorCode.CONTENT_BLOCKED
    # file untouched and the transaction is preserved (still abortable)
    assert f.read_text() == original
    ab = await async_abort(AbortRequest(txn_id=q.txn_id), tm, USER)
    assert ab.status == "ok" and ab.discarded is True


@pytest.mark.asyncio
async def test_commit_allows_nonsecret_match_with_scanner(base_dir, pv, lm, hr, tm):
    # A scanner present must not block edits over non-sensitive regions.
    scanner = ContentScanner(rules=_default_content_scan_rules(), enabled=True)
    f = base_dir / "l.txt"
    write(f, "region = us-east-1\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern="region", replacement="zone"),
        pv, lm, tm, USER, content_scanner=scanner,
    )
    c = await async_commit(CommitRequest(txn_id=q.txn_id), pv, lm, hr, tm, USER, content_scanner=scanner)
    assert c.status == "ok" and c.applied_count == 1
    assert f.read_text() == "zone = us-east-1\n"


@pytest.mark.asyncio
async def test_query_preview_redacts_secret(base_dir, pv, lm, tm):
    scanner = ContentScanner(rules=_default_content_scan_rules(), enabled=True)
    f = base_dir / "j.txt"
    write(f, "key = AKIAIOSFODNN7EXAMPLE end")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern="AKIA[0-9A-Z]{16}", replacement="ROTATED"),
        pv, lm, tm, USER, content_scanner=scanner,
    )
    assert q.status == "ok" and q.match_count == 1
    # the raw key must not appear in the preview's before text
    assert "AKIAIOSFODNN7EXAMPLE" not in q.matches[0].before


# --- F9: self-describing commit + read-only txn status ----------------------


@pytest.mark.asyncio
async def test_commit_reports_applied_ids_and_ttl(base_dir, pv, lm, hr, tm):
    # A subset commit names the exact ids applied and the remaining TTL; a full
    # commit names all applied ids and clears the txn-scoped fields.
    f = base_dir / "f9a.txt"
    write(f, "func_alpha()\nfunc_beta()\nfunc_gamma()\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"func_(\w+)\(\)", replacement=r"method_\1()", ttl=600.0),
        pv, lm, tm, USER,
    )
    c1 = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2]), pv, lm, hr, tm, USER)
    assert c1.status == "ok"
    assert c1.applied_match_ids == [2] and c1.applied_count == 1
    assert c1.remaining_match_ids == [1, 3]
    assert c1.ignored_match_ids is None
    assert c1.ttl_remaining is not None and 0 < c1.ttl_remaining <= 600.0
    # final commit consumes the txn -> txn-scoped fields go None
    c2 = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[1, 3]), pv, lm, hr, tm, USER)
    assert c2.status == "ok"
    assert sorted(c2.applied_match_ids) == [1, 3]
    assert c2.txn_id is None and c2.remaining_match_ids is None and c2.ttl_remaining is None


@pytest.mark.asyncio
async def test_commit_reports_ignored_already_applied_id(base_dir, pv, lm, hr, tm):
    # Re-requesting an id applied by an earlier subset commit is reported as
    # ignored (not silently folded into the count).
    f = base_dir / "f9b.txt"
    write(f, "func_alpha()\nfunc_beta()\nfunc_gamma()\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"func_(\w+)\(\)", replacement=r"method_\1()"),
        pv, lm, tm, USER,
    )
    await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2]), pv, lm, hr, tm, USER)
    # 2 is gone now; request [2, 3] -> only 3 applies, 2 reported ignored
    c = await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2, 3]), pv, lm, hr, tm, USER)
    assert c.status == "ok"
    assert c.applied_match_ids == [3]
    assert c.ignored_match_ids == [2]
    assert c.remaining_match_ids == [1]


@pytest.mark.asyncio
async def test_txn_status_all_locatable_unchanged(base_dir, pv, lm, tm):
    f = base_dir / "f9c.txt"
    h = write(f, "func_alpha()\nfunc_beta()\nfunc_gamma()\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"func_(\w+)\(\)", replacement=r"method_\1()"),
        pv, lm, tm, USER,
    )
    s = await async_txn_status(TxnStatusRequest(txn_id=q.txn_id), pv, lm, tm, USER)
    assert s.status == "ok"
    assert s.file_changed is False and s.current_hash == h == s.base_hash
    assert s.match_count == 3
    assert s.locatable_match_ids == [1, 2, 3] and s.stale_match_ids == []
    assert [m.line for m in s.matches] == [1, 2, 3]
    assert all(m.locatable for m in s.matches)
    assert s.ttl_remaining > 0


@pytest.mark.asyncio
async def test_txn_status_predicts_stale(base_dir, pv, lm, tm):
    # An external ambiguous rewrite makes the match unlocatable; txn_status
    # predicts the stale_conflict commit would hit, without writing.
    f = base_dir / "f9d.txt"
    write(f, "uniquePrefix TARGET uniqueSuffix")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern="TARGET", replacement="DONE"), pv, lm, tm, USER)
    write(f, "TARGET TARGET TARGET")  # anchor gone, TARGET now ambiguous
    s = await async_txn_status(TxnStatusRequest(txn_id=q.txn_id), pv, lm, tm, USER)
    assert s.status == "ok" and s.file_changed is True
    assert s.stale_match_ids == [1] and s.locatable_match_ids == []
    assert s.matches[0].locatable is False and s.matches[0].line is None


@pytest.mark.asyncio
async def test_txn_status_after_subset_commit(base_dir, pv, lm, hr, tm):
    # After a subset commit the open txn shows only the unapplied matches,
    # relocated against the now-changed file.
    f = base_dir / "f9e.txt"
    write(f, "func_alpha()\nfunc_beta()\nfunc_gamma()\n")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern=r"func_(\w+)\(\)", replacement=r"method_\1()"),
        pv, lm, tm, USER,
    )
    await async_commit(CommitRequest(txn_id=q.txn_id, match_ids=[2]), pv, lm, hr, tm, USER)
    s = await async_txn_status(TxnStatusRequest(txn_id=q.txn_id), pv, lm, tm, USER)
    assert s.status == "ok" and s.file_changed is True
    assert s.match_count == 2
    assert s.locatable_match_ids == [1, 3] and s.stale_match_ids == []


@pytest.mark.asyncio
async def test_txn_status_redacts_secret(base_dir, pv, lm, tm):
    scanner = ContentScanner(rules=_default_content_scan_rules(), enabled=True)
    f = base_dir / "f9f.txt"
    write(f, "key = AKIAIOSFODNN7EXAMPLE end")
    q = await async_query_replace(
        QueryReplaceRequest(path=str(f), pattern="AKIA[0-9A-Z]{16}", replacement="ROTATED"),
        pv, lm, tm, USER, content_scanner=scanner,
    )
    s = await async_txn_status(TxnStatusRequest(txn_id=q.txn_id), pv, lm, tm, USER, content_scanner=scanner)
    assert s.status == "ok"
    assert "AKIAIOSFODNN7EXAMPLE" not in s.matches[0].before
    assert s.redactions is not None and len(s.redactions) >= 1


@pytest.mark.asyncio
async def test_txn_status_unknown_txn(base_dir, pv, lm, tm):
    s = await async_txn_status(TxnStatusRequest(txn_id="deadbeef"), pv, lm, tm, USER)
    assert s.status == "error" and s.error_code == ErrorCode.TXN_NOT_FOUND


@pytest.mark.asyncio
async def test_txn_status_cross_user_isolation(base_dir, pv, lm, tm):
    f = base_dir / "f9g.txt"
    write(f, "foo")
    q = await async_query_replace(QueryReplaceRequest(path=str(f), pattern="foo", replacement="X"), pv, lm, tm, "userA")
    s = await async_txn_status(TxnStatusRequest(txn_id=q.txn_id), pv, lm, tm, "userB")
    assert s.status == "error" and s.error_code == ErrorCode.TXN_NOT_FOUND
