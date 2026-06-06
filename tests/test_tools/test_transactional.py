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
from async_crud_mcp.models import AbortRequest, AmendRequest, CommitRequest, ErrorCode, QueryReplaceRequest
from async_crud_mcp.tools import async_abort, async_amend, async_commit, async_query_replace

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
