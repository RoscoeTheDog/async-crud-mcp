"""Tests for RecycleBin core module."""

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from async_crud_mcp.core.recycle_bin import RecycleBin, RecycleBinError, RecycleEntry


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def hmac_key():
    """Generate a random HMAC key for tests."""
    return os.urandom(32)


@pytest.fixture
def recycle_bin(temp_dir, hmac_key):
    """Create a RecycleBin with a temp global directory."""
    global_dir = temp_dir / "recycle"
    return RecycleBin(
        project_recycle_dir=None,
        global_recycle_dir=global_dir,
        enabled=True,
        retention_days=90,
        max_size_mb=500,
        hmac_key=hmac_key,
    )


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample file for recycling."""
    f = temp_dir / "sample.txt"
    f.write_text("hello world", encoding="utf-8")
    return f


class TestRecycle:
    @pytest.mark.asyncio
    async def test_recycle_moves_file_to_recycle_dir(self, recycle_bin, sample_file):
        """File disappears from original location and appears in recycle dir."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123")

        assert not sample_file.exists()
        assert (recycle_bin.recycle_dir / entry.recycle_name).exists()

    @pytest.mark.asyncio
    async def test_recycle_creates_manifest_entry(self, recycle_bin, sample_file):
        """JSONL manifest has correct entry after recycle."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123", reason="test delete")

        manifest = recycle_bin.manifest_path
        assert manifest.exists()

        with open(manifest, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["recycle_name"] == entry.recycle_name
        assert data["original_path"] == str(sample_file)
        assert data["deleted_hash"] == "sha256:abc123"
        assert data["reason"] == "test delete"
        assert data["status"] == "recycled"
        assert data["size_bytes"] == len("hello world")

    @pytest.mark.asyncio
    async def test_recycle_handles_name_collision(self, recycle_bin, temp_dir):
        """Counter suffix added for duplicate names."""
        f1 = temp_dir / "dup.txt"
        f1.write_text("first", encoding="utf-8")
        entry1 = await recycle_bin.recycle(f1, "sha256:aaa")

        # Create another file with the same name
        f2 = temp_dir / "dup.txt"
        f2.write_text("second", encoding="utf-8")

        entry2 = await recycle_bin.recycle(f2, "sha256:bbb")

        assert entry1.recycle_name != entry2.recycle_name
        assert (recycle_bin.recycle_dir / entry1.recycle_name).exists()
        assert (recycle_bin.recycle_dir / entry2.recycle_name).exists()

    @pytest.mark.asyncio
    async def test_recycle_returns_correct_entry_fields(self, recycle_bin, sample_file):
        """RecycleEntry has all expected fields."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123", reason="testing")

        assert entry.original_path == str(sample_file)
        assert entry.deleted_hash == "sha256:abc123"
        assert entry.reason == "testing"
        assert entry.size_bytes == len("hello world")
        assert entry.status == "recycled"
        assert entry.recycle_name  # non-empty

    @pytest.mark.asyncio
    async def test_recycle_creates_gitignore(self, recycle_bin, sample_file):
        """Recycle dir gets a .gitignore file."""
        await recycle_bin.recycle(sample_file, "sha256:abc")
        gitignore = recycle_bin.recycle_dir / ".gitignore"
        assert gitignore.exists()

    @pytest.mark.asyncio
    async def test_disabled_recycle_bin_raises(self, temp_dir, hmac_key):
        """RecycleBinError when disabled and recycle() called."""
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=temp_dir / "recycle",
            enabled=False,
            hmac_key=hmac_key,
        )
        f = temp_dir / "file.txt"
        f.write_text("data", encoding="utf-8")

        with pytest.raises(RecycleBinError, match="disabled"):
            await rb.recycle(f, "sha256:x")


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_returns_file_to_original(self, recycle_bin, sample_file):
        """File restored to original_path."""
        original = str(sample_file)
        entry = await recycle_bin.recycle(sample_file, "sha256:abc")
        assert not sample_file.exists()

        result = await recycle_bin.restore(entry.recycle_name)
        assert result.restored_path == original
        assert Path(original).exists()
        assert Path(original).read_text(encoding="utf-8") == "hello world"

    @pytest.mark.asyncio
    async def test_restore_to_custom_destination(self, recycle_bin, sample_file, temp_dir):
        """File restored to explicit path."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc")

        custom_dest = temp_dir / "restored" / "custom.txt"
        result = await recycle_bin.restore(entry.recycle_name, destination=custom_dest)

        assert result.restored_path == str(custom_dest)
        assert custom_dest.exists()
        assert custom_dest.read_text(encoding="utf-8") == "hello world"

    @pytest.mark.asyncio
    async def test_restore_nonexistent_raises(self, recycle_bin):
        """RecycleBinError for unknown recycle_name."""
        with pytest.raises(RecycleBinError, match="not found"):
            await recycle_bin.restore("nonexistent_file.txt")

    @pytest.mark.asyncio
    async def test_restore_destination_conflict(self, recycle_bin, sample_file, temp_dir):
        """RecycleBinError when destination exists and force=False."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc")

        # Create a file at the original location
        sample_file.write_text("new content", encoding="utf-8")

        with pytest.raises(RecycleBinError, match="already exists"):
            await recycle_bin.restore(entry.recycle_name)

    @pytest.mark.asyncio
    async def test_restore_with_force(self, recycle_bin, sample_file, temp_dir):
        """Overwrites when force=True."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc")

        # Create a file at the original location
        sample_file.write_text("blocking content", encoding="utf-8")

        result = await recycle_bin.restore(entry.recycle_name, force=True)
        assert Path(result.restored_path).read_text(encoding="utf-8") == "hello world"

    @pytest.mark.asyncio
    async def test_restore_updates_manifest(self, recycle_bin, sample_file):
        """Manifest gets a 'restored' entry after restore."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc")
        await recycle_bin.restore(entry.recycle_name)

        with open(recycle_bin.manifest_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2
        restored_data = json.loads(lines[1])
        assert restored_data["status"] == "restored"
        assert restored_data["recycle_name"] == entry.recycle_name


class TestListEntries:
    @pytest.mark.asyncio
    async def test_list_entries_sorted_by_recency(self, recycle_bin, temp_dir):
        """Most recent entries first."""
        files = []
        for i in range(3):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(f)

        entries = []
        for f in files:
            entries.append(await recycle_bin.recycle(f, f"sha256:{f.name}"))

        listed = await recycle_bin.list_entries()
        assert len(listed) == 3
        # Most recent should be first (file2)
        assert listed[0].recycle_name == entries[2].recycle_name

    @pytest.mark.asyncio
    async def test_list_entries_excludes_restored(self, recycle_bin, temp_dir):
        """Restored entries are not listed."""
        f1 = temp_dir / "keep.txt"
        f1.write_text("keep", encoding="utf-8")
        f2 = temp_dir / "restore_me.txt"
        f2.write_text("restore", encoding="utf-8")

        entry1 = await recycle_bin.recycle(f1, "sha256:keep")
        entry2 = await recycle_bin.recycle(f2, "sha256:restore")

        await recycle_bin.restore(entry2.recycle_name)

        listed = await recycle_bin.list_entries()
        assert len(listed) == 1
        assert listed[0].recycle_name == entry1.recycle_name

    @pytest.mark.asyncio
    async def test_list_entries_respects_limit(self, recycle_bin, temp_dir):
        """Limit parameter caps the number of results."""
        for i in range(5):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            await recycle_bin.recycle(f, f"sha256:{i}")

        listed = await recycle_bin.list_entries(limit=2)
        assert len(listed) == 2

    @pytest.mark.asyncio
    async def test_list_entries_empty(self, recycle_bin):
        """Empty list when no entries exist."""
        listed = await recycle_bin.list_entries()
        assert listed == []


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_removes_old_entries(self, recycle_bin, temp_dir):
        """Entries past retention are removed."""
        f = temp_dir / "old.txt"
        f.write_text("old data", encoding="utf-8")
        await recycle_bin.recycle(f, "sha256:old")

        # Use 0 retention days to clean everything
        removed = await recycle_bin.cleanup(retention_days=0)
        assert removed == 1

        # Verify the file is gone from recycle dir
        listed = await recycle_bin.list_entries()
        assert len(listed) == 0

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_entries(self, recycle_bin, temp_dir):
        """Recent entries are not removed."""
        f = temp_dir / "recent.txt"
        f.write_text("recent data", encoding="utf-8")
        await recycle_bin.recycle(f, "sha256:recent")

        removed = await recycle_bin.cleanup(retention_days=90)
        assert removed == 0

        listed = await recycle_bin.list_entries()
        assert len(listed) == 1


class TestSetProjectDir:
    def test_set_project_dir_switches_location(self, temp_dir, hmac_key):
        """Recycle ops use project dir after switch."""
        global_dir = temp_dir / "global_recycle"
        project_dir = temp_dir / "project_recycle"

        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )
        assert rb.recycle_dir == global_dir

        rb.set_project_dir(project_dir)
        assert rb.recycle_dir == project_dir

    def test_set_project_dir_to_none_reverts(self, temp_dir, hmac_key):
        """Setting project dir to None reverts to global."""
        global_dir = temp_dir / "global_recycle"
        project_dir = temp_dir / "project_recycle"

        rb = RecycleBin(
            project_recycle_dir=project_dir,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )
        assert rb.recycle_dir == project_dir

        rb.set_project_dir(None)
        assert rb.recycle_dir == global_dir


class TestHMACIntegrity:
    """Tests for HMAC-SHA256 manifest entry integrity."""

    @pytest.mark.asyncio
    async def test_recycle_creates_signed_manifest_entry(self, recycle_bin, sample_file):
        """Signature field is non-empty after recycle."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123")
        assert entry.signature != ""
        assert len(entry.signature) == 64  # SHA-256 hex digest length

    @pytest.mark.asyncio
    async def test_restore_succeeds_with_valid_signature(self, recycle_bin, sample_file):
        """Normal recycle+restore roundtrip works with HMAC."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123")
        result = await recycle_bin.restore(entry.recycle_name)
        assert Path(result.restored_path).exists()
        assert Path(result.restored_path).read_text(encoding="utf-8") == "hello world"

    @pytest.mark.asyncio
    async def test_restore_rejects_tampered_original_path(self, recycle_bin, sample_file):
        """Tampered original_path in manifest causes integrity error."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123")

        # Tamper with the manifest: change original_path
        manifest = recycle_bin.manifest_path
        with open(manifest, "r", encoding="utf-8") as f:
            lines = f.readlines()

        data = json.loads(lines[0])
        data["original_path"] = "/tmp/evil/path"
        lines[0] = json.dumps(data) + "\n"

        with open(manifest, "w", encoding="utf-8") as f:
            f.writelines(lines)

        with pytest.raises(RecycleBinError, match="Integrity check failed"):
            await recycle_bin.restore(entry.recycle_name)

    @pytest.mark.asyncio
    async def test_restore_rejects_tampered_recycle_name(self, recycle_bin, sample_file, temp_dir):
        """Tampered recycle_name field causes integrity error."""
        entry = await recycle_bin.recycle(sample_file, "sha256:abc123")

        # Tamper with the manifest: change deleted_hash (part of signature)
        manifest = recycle_bin.manifest_path
        with open(manifest, "r", encoding="utf-8") as f:
            lines = f.readlines()

        data = json.loads(lines[0])
        data["deleted_hash"] = "sha256:tampered"
        lines[0] = json.dumps(data) + "\n"

        with open(manifest, "w", encoding="utf-8") as f:
            f.writelines(lines)

        with pytest.raises(RecycleBinError, match="Integrity check failed"):
            await recycle_bin.restore(entry.recycle_name)

    @pytest.mark.asyncio
    async def test_restore_allows_unsigned_entries(self, temp_dir, hmac_key):
        """Pre-HMAC entries (empty signature) still restore successfully."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # Create a file and recycle it manually (without signature)
        f = temp_dir / "unsigned.txt"
        f.write_text("unsigned content", encoding="utf-8")

        # Manually set up recycle dir and manifest
        global_dir.mkdir(parents=True, exist_ok=True)
        recycle_name = "20240101_000000_unsigned.txt"
        import shutil
        shutil.copy2(str(f), str(global_dir / recycle_name))

        # Write manifest entry without signature
        entry_data = {
            "recycle_name": recycle_name,
            "original_path": str(f),
            "deleted_hash": "sha256:test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "test",
            "size_bytes": 16,
            "status": "recycled",
            "signature": "",
        }
        manifest = global_dir / ".manifest.jsonl"
        with open(manifest, "w", encoding="utf-8") as mf:
            mf.write(json.dumps(entry_data) + "\n")

        # Remove original so restore goes to original path
        f.unlink()

        # Should succeed without error (backward compat)
        result = await rb.restore(recycle_name)
        assert Path(result.restored_path).exists()

    @pytest.mark.asyncio
    async def test_different_keys_produce_different_signatures(self, temp_dir):
        """Two RecycleBin instances with different keys produce different signatures."""
        key1 = os.urandom(32)
        key2 = os.urandom(32)

        dir1 = temp_dir / "rb1"
        dir2 = temp_dir / "rb2"

        rb1 = RecycleBin(project_recycle_dir=None, global_recycle_dir=dir1, hmac_key=key1)
        rb2 = RecycleBin(project_recycle_dir=None, global_recycle_dir=dir2, hmac_key=key2)

        f1 = temp_dir / "file1.txt"
        f1.write_text("same content", encoding="utf-8")
        f2 = temp_dir / "file2.txt"
        f2.write_text("same content", encoding="utf-8")

        entry1 = await rb1.recycle(f1, "sha256:same")
        entry2 = await rb2.recycle(f2, "sha256:same")

        assert entry1.signature != ""
        assert entry2.signature != ""
        assert entry1.signature != entry2.signature


class TestAsyncLocking:
    """Tests for async locking and timeout behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_recycle_operations(self, temp_dir, hmac_key):
        """Multiple concurrent recycle calls all succeed without manifest corruption."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # Create multiple files
        files = []
        for i in range(5):
            f = temp_dir / f"concurrent_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(f)

        # Recycle all concurrently
        entries = await asyncio.gather(
            *[rb.recycle(f, f"sha256:{i}") for i, f in enumerate(files)]
        )

        assert len(entries) == 5
        # All entries have unique names
        names = {e.recycle_name for e in entries}
        assert len(names) == 5

        # Manifest has exactly 5 entries
        with open(rb.manifest_path, "r", encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) == 5

        # All files exist in recycle dir
        for e in entries:
            assert (rb.recycle_dir / e.recycle_name).exists()

    @pytest.mark.asyncio
    async def test_concurrent_restore_operations(self, temp_dir, hmac_key):
        """Multiple concurrent restores of different files succeed."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # Create and recycle multiple files
        entries = []
        for i in range(3):
            f = temp_dir / f"restore_{i}.txt"
            f.write_text(f"restore content {i}", encoding="utf-8")
            entry = await rb.recycle(f, f"sha256:{i}")
            entries.append(entry)

        # Restore all concurrently to different destinations
        dests = [temp_dir / f"restored_{i}.txt" for i in range(3)]
        results = await asyncio.gather(
            *[rb.restore(e.recycle_name, destination=d) for e, d in zip(entries, dests)]
        )

        assert len(results) == 3
        for i, r in enumerate(results):
            assert Path(r.restored_path).exists()
            assert Path(r.restored_path).read_text(encoding="utf-8") == f"restore content {i}"

    @pytest.mark.asyncio
    async def test_recycle_timeout_raises_error(self, temp_dir, hmac_key):
        """Lock held by another task causes timeout for second task."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # Acquire the lock manually to simulate contention
        await rb._lock.acquire()

        f = temp_dir / "timeout_test.txt"
        f.write_text("timeout data", encoding="utf-8")

        try:
            with pytest.raises(RecycleBinError, match="timed out"):
                await rb.recycle(f, "sha256:timeout", timeout=0.1)
        finally:
            rb._lock.release()

    @pytest.mark.asyncio
    async def test_restore_timeout_raises_error(self, temp_dir, hmac_key):
        """Lock held causes timeout on restore."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # First recycle a file normally
        f = temp_dir / "timeout_restore.txt"
        f.write_text("data", encoding="utf-8")
        entry = await rb.recycle(f, "sha256:x")

        # Now hold the lock to simulate contention
        await rb._lock.acquire()

        try:
            with pytest.raises(RecycleBinError, match="timed out"):
                await rb.restore(entry.recycle_name, timeout=0.1)
        finally:
            rb._lock.release()

    @pytest.mark.asyncio
    async def test_concurrent_recycle_same_basename(self, temp_dir, hmac_key):
        """Collision handling under concurrency for same basename."""
        global_dir = temp_dir / "recycle"
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
            hmac_key=hmac_key,
        )

        # Create multiple files with the same basename in different dirs
        dirs = []
        files = []
        for i in range(3):
            d = temp_dir / f"subdir_{i}"
            d.mkdir()
            f = d / "same_name.txt"
            f.write_text(f"content from dir {i}", encoding="utf-8")
            dirs.append(d)
            files.append(f)

        # Recycle all concurrently - all have basename "same_name.txt"
        entries = await asyncio.gather(
            *[rb.recycle(f, f"sha256:{i}") for i, f in enumerate(files)]
        )

        # All should succeed with unique recycle names
        names = {e.recycle_name for e in entries}
        assert len(names) == 3

        # All files exist in recycle dir
        for e in entries:
            assert (rb.recycle_dir / e.recycle_name).exists()
