"""Tests for atomic file I/O operations and SHA-256 hashing."""

import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from async_crud_mcp.core.file_io import (
    HashRegistry,
    atomic_write,
    compute_file_hash,
    compute_hash,
    safe_rename,
)


class TestComputeHash:
    """Tests for compute_hash function."""

    def test_hash_format(self):
        """Test hash output format is 'sha256:<hex>'."""
        data = b"hello world"
        result = compute_hash(data)
        assert result.startswith("sha256:")
        assert len(result) == 71  # "sha256:" (7 chars) + 64 hex chars

    def test_deterministic_output(self):
        """Test same input produces same hash."""
        data = b"test data"
        hash1 = compute_hash(data)
        hash2 = compute_hash(data)
        assert hash1 == hash2

    def test_empty_bytes_hash(self):
        """Test hashing empty bytes."""
        result = compute_hash(b"")
        expected = f"sha256:{hashlib.sha256(b'').hexdigest()}"
        assert result == expected

    def test_large_content_hash(self):
        """Test hashing large content."""
        data = b"x" * 1024 * 1024  # 1MB
        result = compute_hash(data)
        expected = f"sha256:{hashlib.sha256(data).hexdigest()}"
        assert result == expected


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_basic_file_hash(self, tmp_path):
        """Test hashing a basic file."""
        file_path = tmp_path / "test.txt"
        content = b"hello world"
        file_path.write_bytes(content)

        result = compute_file_hash(str(file_path))
        expected = compute_hash(content)
        assert result == expected

    def test_file_not_found(self):
        """Test error when file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            compute_file_hash("/nonexistent/file.txt")

    def test_mixed_line_endings(self, tmp_path):
        """Test hashing preserves line endings (no normalization)."""
        file_unix = tmp_path / "unix.txt"
        file_windows = tmp_path / "windows.txt"

        content_unix = b"line1\nline2\n"
        content_windows = b"line1\r\nline2\r\n"

        file_unix.write_bytes(content_unix)
        file_windows.write_bytes(content_windows)

        hash_unix = compute_file_hash(str(file_unix))
        hash_windows = compute_file_hash(str(file_windows))

        # Different line endings should produce different hashes
        assert hash_unix != hash_windows
        assert hash_unix == compute_hash(content_unix)
        assert hash_windows == compute_hash(content_windows)

    def test_file_size_limit(self, tmp_path):
        """Test max file size enforcement."""
        file_path = tmp_path / "large.bin"
        # Create file larger than default 10MB limit
        large_content = b"x" * (11 * 1024 * 1024)
        file_path.write_bytes(large_content)

        with pytest.raises(ValueError, match="exceeds max"):
            compute_file_hash(str(file_path))

    def test_custom_size_limit(self, tmp_path):
        """Test custom max file size."""
        file_path = tmp_path / "test.bin"
        content = b"x" * 100
        file_path.write_bytes(content)

        # Should succeed with higher limit
        result = compute_file_hash(str(file_path), max_file_size_bytes=200)
        assert result.startswith("sha256:")

        # Should fail with lower limit
        with pytest.raises(ValueError):
            compute_file_hash(str(file_path), max_file_size_bytes=50)


class TestAtomicWrite:
    """Tests for atomic_write function."""

    def test_basic_write(self, tmp_path):
        """Test basic file creation."""
        target = tmp_path / "test.txt"
        content = b"hello world"

        atomic_write(str(target), content)

        assert target.exists()
        assert target.read_bytes() == content

    def test_overwrite_existing(self, tmp_path):
        """Test overwriting existing file atomically."""
        target = tmp_path / "existing.txt"
        target.write_bytes(b"old content")

        new_content = b"new content"
        atomic_write(str(target), new_content)

        assert target.read_bytes() == new_content

    def test_unicode_content(self, tmp_path):
        """Test writing unicode content (as bytes)."""
        target = tmp_path / "unicode.txt"
        content = "Hello \u4e16\u754c".encode('utf-8')

        atomic_write(str(target), content)

        assert target.read_bytes() == content
        assert target.read_text(encoding='utf-8') == "Hello \u4e16\u754c"

    def test_temp_file_cleanup_on_failure(self, tmp_path):
        """Test temp file is cleaned up on write failure."""
        target = tmp_path / "test.txt"

        with patch('os.write', side_effect=OSError("Write failed")):
            with pytest.raises(OSError, match="Write failed"):
                atomic_write(str(target), b"content")

        # No temp files should remain
        temp_files = list(tmp_path.glob(".tmp_*"))
        assert len(temp_files) == 0

    def test_creates_new_file(self, tmp_path):
        """Test creating new file in existing directory."""
        target = tmp_path / "subdir" / "new.txt"
        target.parent.mkdir(parents=True, exist_ok=True)

        atomic_write(str(target), b"content")
        assert target.exists()


class TestReplaceWithRetry:
    """Tests for _replace_with_retry function (via atomic_write)."""

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows-specific test")
    def test_windows_permission_retry(self, tmp_path):
        """Test Windows PermissionError retry logic."""
        target = tmp_path / "test.txt"
        content = b"test content"

        # Mock os.replace to fail once then succeed
        original_replace = os.replace
        call_count = 0

        def mock_replace(src, dst):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("Locked by antivirus")
            return original_replace(src, dst)

        with patch('os.replace', side_effect=mock_replace):
            atomic_write(str(target), content)

        assert target.read_bytes() == content
        assert call_count == 2  # Failed once, succeeded on retry

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows-specific test")
    def test_max_retries_exceeded(self, tmp_path):
        """Test failure after max retries on Windows."""
        target = tmp_path / "test.txt"
        content = b"test content"

        with patch('os.replace', side_effect=PermissionError("Permanently locked")):
            with pytest.raises(PermissionError, match="Permanently locked"):
                atomic_write(str(target), content)


class TestCrossFilesystemFallback:
    """Tests for cross-filesystem rename fallback."""

    def test_same_filesystem(self, tmp_path):
        """Test normal rename on same filesystem."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_bytes(b"content")

        result = safe_rename(str(src), str(dst))

        assert result is False  # No cross-filesystem fallback
        assert not src.exists()
        assert dst.exists()
        assert dst.read_bytes() == b"content"

    def test_cross_filesystem_detection(self, tmp_path):
        """Test cross-filesystem detection via mocked st_dev."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_bytes(b"content")

        # Mock stat to return different st_dev values
        original_stat = os.stat

        def mock_stat(path):
            stat_result = original_stat(path)
            if str(src) in str(path):
                # Source on device 1
                return os.stat_result((stat_result.st_mode, stat_result.st_ino, 1,
                                       stat_result.st_nlink, stat_result.st_uid,
                                       stat_result.st_gid, stat_result.st_size,
                                       stat_result.st_atime, stat_result.st_mtime,
                                       stat_result.st_ctime))
            else:
                # Dest on device 2
                return os.stat_result((stat_result.st_mode, stat_result.st_ino, 2,
                                       stat_result.st_nlink, stat_result.st_uid,
                                       stat_result.st_gid, stat_result.st_size,
                                       stat_result.st_atime, stat_result.st_mtime,
                                       stat_result.st_ctime))

        with patch('os.stat', side_effect=mock_stat):
            result = safe_rename(str(src), str(dst))

        assert result is True  # Cross-filesystem fallback used
        assert not src.exists()
        assert dst.exists()
        assert dst.read_bytes() == b"content"


class TestFsyncParentDirectory:
    """Tests for parent directory fsync (via atomic_write)."""

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS-specific test")
    def test_linux_fsync_parent(self, tmp_path):
        """Test parent directory fsync is called on Linux."""
        target = tmp_path / "test.txt"

        with patch('os.fsync') as mock_fsync:
            atomic_write(str(target), b"content")

            # Should have called fsync at least twice:
            # once for file, once for parent directory
            assert mock_fsync.call_count >= 2

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows-specific test")
    def test_windows_skips_fsync_parent(self, tmp_path):
        """Test parent directory fsync is skipped on Windows."""
        target = tmp_path / "test.txt"

        with patch('os.open', wraps=os.open) as mock_open:
            atomic_write(str(target), b"content")

            # On Windows, should not try to open parent directory with O_RDONLY
            for call in mock_open.call_args_list:
                if len(call[0]) > 1:
                    assert call[0][1] != os.O_RDONLY or not Path(call[0][0]).is_dir()


class TestHashRegistry:
    """Tests for HashRegistry class."""

    def test_get_update_remove(self):
        """Test basic get/update/remove operations."""
        registry = HashRegistry()

        # Initially empty
        assert registry.get("/path/to/file") is None

        # Update and retrieve
        registry.update("/path/to/file", "sha256:abc123")
        assert registry.get("/path/to/file") == "sha256:abc123"

        # Remove
        registry.remove("/path/to/file")
        assert registry.get("/path/to/file") is None

    def test_path_normalization(self, tmp_path):
        """Test path normalization for consistent lookups."""
        registry = HashRegistry()

        # Create a real file to test with realpath
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"content")

        # Different path representations should normalize to same key
        path1 = str(test_file)
        path2 = str(test_file.resolve())

        registry.update(path1, "sha256:hash1")
        assert registry.get(path2) == "sha256:hash1"

    def test_snapshot_restore(self):
        """Test snapshot and restore functionality."""
        registry = HashRegistry()

        # Add some entries
        registry.update("/file1", "sha256:hash1")
        registry.update("/file2", "sha256:hash2")

        # Take snapshot
        snapshot = registry.snapshot()
        assert len(snapshot) == 2

        # Modify registry
        registry.update("/file3", "sha256:hash3")
        registry.remove("/file1")

        # Restore from snapshot
        registry.restore(snapshot)
        assert registry.get("/file1") == "sha256:hash1"
        assert registry.get("/file2") == "sha256:hash2"
        assert registry.get("/file3") is None

    def test_snapshot_is_copy(self):
        """Test that snapshot returns a copy, not reference."""
        registry = HashRegistry()
        registry.update("/file", "sha256:hash1")

        snapshot = registry.snapshot()
        snapshot["/file"] = "sha256:modified"

        # Original should be unchanged
        assert registry.get("/file") == "sha256:hash1"
