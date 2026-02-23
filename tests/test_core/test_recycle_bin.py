"""Tests for RecycleBin core module."""

import json
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
def recycle_bin(temp_dir):
    """Create a RecycleBin with a temp global directory."""
    global_dir = temp_dir / "recycle"
    return RecycleBin(
        project_recycle_dir=None,
        global_recycle_dir=global_dir,
        enabled=True,
        retention_days=90,
        max_size_mb=500,
    )


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample file for recycling."""
    f = temp_dir / "sample.txt"
    f.write_text("hello world", encoding="utf-8")
    return f


class TestRecycle:
    def test_recycle_moves_file_to_recycle_dir(self, recycle_bin, sample_file):
        """File disappears from original location and appears in recycle dir."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc123")

        assert not sample_file.exists()
        assert (recycle_bin.recycle_dir / entry.recycle_name).exists()

    def test_recycle_creates_manifest_entry(self, recycle_bin, sample_file):
        """JSONL manifest has correct entry after recycle."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc123", reason="test delete")

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

    def test_recycle_handles_name_collision(self, recycle_bin, temp_dir):
        """Counter suffix added for duplicate names."""
        f1 = temp_dir / "dup.txt"
        f1.write_text("first", encoding="utf-8")
        entry1 = recycle_bin.recycle(f1, "sha256:aaa")

        # Create another file with the same name
        f2 = temp_dir / "dup.txt"
        f2.write_text("second", encoding="utf-8")

        # Manually create a file in recycle that would match the next timestamp
        # to force a collision - we simulate by creating a file with the same name
        # pattern. Since both happen within the same second, the name generator
        # will add a counter.
        entry2 = recycle_bin.recycle(f2, "sha256:bbb")

        assert entry1.recycle_name != entry2.recycle_name
        assert (recycle_bin.recycle_dir / entry1.recycle_name).exists()
        assert (recycle_bin.recycle_dir / entry2.recycle_name).exists()

    def test_recycle_returns_correct_entry_fields(self, recycle_bin, sample_file):
        """RecycleEntry has all expected fields."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc123", reason="testing")

        assert entry.original_path == str(sample_file)
        assert entry.deleted_hash == "sha256:abc123"
        assert entry.reason == "testing"
        assert entry.size_bytes == len("hello world")
        assert entry.status == "recycled"
        assert entry.recycle_name  # non-empty

    def test_recycle_creates_gitignore(self, recycle_bin, sample_file):
        """Recycle dir gets a .gitignore file."""
        recycle_bin.recycle(sample_file, "sha256:abc")
        gitignore = recycle_bin.recycle_dir / ".gitignore"
        assert gitignore.exists()

    def test_disabled_recycle_bin_raises(self, temp_dir):
        """RecycleBinError when disabled and recycle() called."""
        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=temp_dir / "recycle",
            enabled=False,
        )
        f = temp_dir / "file.txt"
        f.write_text("data", encoding="utf-8")

        with pytest.raises(RecycleBinError, match="disabled"):
            rb.recycle(f, "sha256:x")


class TestRestore:
    def test_restore_returns_file_to_original(self, recycle_bin, sample_file):
        """File restored to original_path."""
        original = str(sample_file)
        entry = recycle_bin.recycle(sample_file, "sha256:abc")
        assert not sample_file.exists()

        result = recycle_bin.restore(entry.recycle_name)
        assert result.restored_path == original
        assert Path(original).exists()
        assert Path(original).read_text(encoding="utf-8") == "hello world"

    def test_restore_to_custom_destination(self, recycle_bin, sample_file, temp_dir):
        """File restored to explicit path."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc")

        custom_dest = temp_dir / "restored" / "custom.txt"
        result = recycle_bin.restore(entry.recycle_name, destination=custom_dest)

        assert result.restored_path == str(custom_dest)
        assert custom_dest.exists()
        assert custom_dest.read_text(encoding="utf-8") == "hello world"

    def test_restore_nonexistent_raises(self, recycle_bin):
        """RecycleBinError for unknown recycle_name."""
        with pytest.raises(RecycleBinError, match="not found"):
            recycle_bin.restore("nonexistent_file.txt")

    def test_restore_destination_conflict(self, recycle_bin, sample_file, temp_dir):
        """RecycleBinError when destination exists and force=False."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc")

        # Create a file at the original location
        sample_file.write_text("new content", encoding="utf-8")

        with pytest.raises(RecycleBinError, match="already exists"):
            recycle_bin.restore(entry.recycle_name)

    def test_restore_with_force(self, recycle_bin, sample_file, temp_dir):
        """Overwrites when force=True."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc")

        # Create a file at the original location
        sample_file.write_text("blocking content", encoding="utf-8")

        result = recycle_bin.restore(entry.recycle_name, force=True)
        assert Path(result.restored_path).read_text(encoding="utf-8") == "hello world"

    def test_restore_updates_manifest(self, recycle_bin, sample_file):
        """Manifest gets a 'restored' entry after restore."""
        entry = recycle_bin.recycle(sample_file, "sha256:abc")
        recycle_bin.restore(entry.recycle_name)

        with open(recycle_bin.manifest_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2
        restored_data = json.loads(lines[1])
        assert restored_data["status"] == "restored"
        assert restored_data["recycle_name"] == entry.recycle_name


class TestListEntries:
    def test_list_entries_sorted_by_recency(self, recycle_bin, temp_dir):
        """Most recent entries first."""
        files = []
        for i in range(3):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(f)

        entries = []
        for f in files:
            entries.append(recycle_bin.recycle(f, f"sha256:{f.name}"))

        listed = recycle_bin.list_entries()
        assert len(listed) == 3
        # Most recent should be first (file2)
        assert listed[0].recycle_name == entries[2].recycle_name

    def test_list_entries_excludes_restored(self, recycle_bin, temp_dir):
        """Restored entries are not listed."""
        f1 = temp_dir / "keep.txt"
        f1.write_text("keep", encoding="utf-8")
        f2 = temp_dir / "restore_me.txt"
        f2.write_text("restore", encoding="utf-8")

        entry1 = recycle_bin.recycle(f1, "sha256:keep")
        entry2 = recycle_bin.recycle(f2, "sha256:restore")

        recycle_bin.restore(entry2.recycle_name)

        listed = recycle_bin.list_entries()
        assert len(listed) == 1
        assert listed[0].recycle_name == entry1.recycle_name

    def test_list_entries_respects_limit(self, recycle_bin, temp_dir):
        """Limit parameter caps the number of results."""
        for i in range(5):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            recycle_bin.recycle(f, f"sha256:{i}")

        listed = recycle_bin.list_entries(limit=2)
        assert len(listed) == 2

    def test_list_entries_empty(self, recycle_bin):
        """Empty list when no entries exist."""
        listed = recycle_bin.list_entries()
        assert listed == []


class TestCleanup:
    def test_cleanup_removes_old_entries(self, recycle_bin, temp_dir):
        """Entries past retention are removed."""
        f = temp_dir / "old.txt"
        f.write_text("old data", encoding="utf-8")
        recycle_bin.recycle(f, "sha256:old")

        # Use 0 retention days to clean everything
        removed = recycle_bin.cleanup(retention_days=0)
        assert removed == 1

        # Verify the file is gone from recycle dir
        listed = recycle_bin.list_entries()
        assert len(listed) == 0

    def test_cleanup_preserves_recent_entries(self, recycle_bin, temp_dir):
        """Recent entries are not removed."""
        f = temp_dir / "recent.txt"
        f.write_text("recent data", encoding="utf-8")
        recycle_bin.recycle(f, "sha256:recent")

        removed = recycle_bin.cleanup(retention_days=90)
        assert removed == 0

        listed = recycle_bin.list_entries()
        assert len(listed) == 1


class TestSetProjectDir:
    def test_set_project_dir_switches_location(self, temp_dir):
        """Recycle ops use project dir after switch."""
        global_dir = temp_dir / "global_recycle"
        project_dir = temp_dir / "project_recycle"

        rb = RecycleBin(
            project_recycle_dir=None,
            global_recycle_dir=global_dir,
        )
        assert rb.recycle_dir == global_dir

        rb.set_project_dir(project_dir)
        assert rb.recycle_dir == project_dir

    def test_set_project_dir_to_none_reverts(self, temp_dir):
        """Setting project dir to None reverts to global."""
        global_dir = temp_dir / "global_recycle"
        project_dir = temp_dir / "project_recycle"

        rb = RecycleBin(
            project_recycle_dir=project_dir,
            global_recycle_dir=global_dir,
        )
        assert rb.recycle_dir == project_dir

        rb.set_project_dir(None)
        assert rb.recycle_dir == global_dir
