"""Atomic file write operations and SHA-256 content hashing.

This module provides cross-platform atomic file operations with durability guarantees:
- atomic_write: Write content via temp file + fsync + os.replace
- compute_hash: SHA-256 content hashing in 'sha256:<hex>' format
- HashRegistry: In-memory mapping of file paths to their latest hashes

Cross-platform concerns:
- Windows PermissionError retry with exponential backoff on os.replace
- Cross-filesystem rename fallback (copy + fsync + delete)
- Parent directory fsync on Linux for durability
- Raw bytes hashing (no line ending normalization)

All functions use stdlib only (hashlib, tempfile, os, shutil) plus tenacity for retry logic.
"""

import hashlib
import os
import shutil
import sys
import tempfile
from typing import Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def compute_hash(data: bytes) -> str:
    """Compute SHA-256 hash of bytes data.

    Args:
        data: Raw bytes to hash (no encoding/normalization applied)

    Returns:
        Hash string in format 'sha256:<64-char-hex-digest>'

    Note:
        No line ending normalization is performed. The same logical content
        will produce different hashes on different platforms if line endings
        differ (\\r\\n vs \\n), which is the correct behavior.
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def compute_file_hash(file_path: str, max_file_size_bytes: int = 10 * 1024 * 1024) -> str:
    """Compute SHA-256 hash of a file's contents.

    Args:
        file_path: Path to file to hash
        max_file_size_bytes: Maximum file size to hash (default 10MB)

    Returns:
        Hash string in format 'sha256:<64-char-hex-digest>'

    Raises:
        FileNotFoundError: If file doesn't exist
        OSError: If file cannot be read
        ValueError: If file exceeds max_file_size_bytes

    Note:
        File is read in binary mode with no line ending normalization.
        Uses hashlib.file_digest() for streaming hash computation (Python 3.11+).
    """
    file_size = os.path.getsize(file_path)
    if file_size > max_file_size_bytes:
        raise ValueError(
            f"File {file_path} size {file_size} exceeds max {max_file_size_bytes} bytes"
        )

    with open(file_path, 'rb') as f:
        digest = hashlib.file_digest(f, 'sha256')

    return f"sha256:{digest.hexdigest()}"


class HashRegistry:
    """In-memory registry mapping normalized file paths to SHA-256 hashes.

    Thread-safe for single-threaded use. Not suitable for multi-process scenarios.
    Path normalization uses os.path.normcase(os.path.normpath(os.path.realpath(path)))
    to ensure consistent path comparison across platforms.
    """

    def __init__(self) -> None:
        """Initialize empty hash registry."""
        self._registry: dict[str, str] = {}

    def _normalize_path(self, path: str) -> str:
        """Normalize path for consistent comparison."""
        return os.path.normcase(os.path.normpath(os.path.realpath(path)))

    def get(self, path: str) -> Optional[str]:
        """Get hash for a file path.

        Args:
            path: File path to lookup

        Returns:
            Hash string in 'sha256:<hex>' format, or None if not found
        """
        normalized = self._normalize_path(path)
        return self._registry.get(normalized)

    def update(self, path: str, hash_value: str) -> None:
        """Update hash for a file path.

        Args:
            path: File path to update
            hash_value: Hash string in 'sha256:<hex>' format
        """
        normalized = self._normalize_path(path)
        self._registry[normalized] = hash_value

    def remove(self, path: str) -> None:
        """Remove a file path from the registry.

        Args:
            path: File path to remove
        """
        normalized = self._normalize_path(path)
        self._registry.pop(normalized, None)

    def snapshot(self) -> dict[str, str]:
        """Get a copy of the current registry state.

        Returns:
            Dictionary mapping normalized paths to hash strings
        """
        return self._registry.copy()

    def restore(self, state: dict[str, str]) -> None:
        """Restore registry state from a snapshot.

        Args:
            state: Dictionary mapping normalized paths to hash strings
        """
        self._registry = state.copy()


def _replace_with_retry(src: str, dst: str) -> None:
    """Replace file atomically with retry on Windows PermissionError.

    Args:
        src: Source file path
        dst: Destination file path

    Raises:
        PermissionError: If all retry attempts fail on Windows
        OSError: If replacement fails for other reasons

    Note:
        On Windows, retries up to 3 attempts with exponential backoff
        (0.05s, 0.1s, 0.2s) to handle transient PermissionError from
        antivirus or file indexing. On other platforms, no retry is used.
    """
    if sys.platform == 'win32':
        @retry(
            retry=retry_if_exception_type(PermissionError),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
            reraise=True
        )
        def _replace_windows() -> None:
            os.replace(src, dst)

        _replace_windows()
    else:
        os.replace(src, dst)


def _fsync_parent_directory(file_path: str) -> None:
    """Fsync parent directory for durability on Linux/macOS.

    Args:
        file_path: Path to file whose parent directory should be synced

    Note:
        On Windows, this is a no-op. On Linux/macOS, opens parent directory
        and calls fsync to ensure directory entry is persisted. Silently
        ignores OSError for filesystems that don't support directory fsync.
    """
    if sys.platform == 'win32':
        return

    parent_dir = os.path.dirname(file_path)
    if not parent_dir:
        return

    try:
        dir_fd = os.open(parent_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        # Some filesystems don't support directory fsync
        pass


def atomic_write(target_path: str, content: bytes) -> None:
    """Write content to file atomically with durability guarantees.

    Args:
        target_path: Destination file path
        content: Raw bytes content to write

    Raises:
        OSError: If write fails
        PermissionError: If file cannot be written (after retries)

    Implementation:
        1. Create temp file in same directory as target (ensures same filesystem)
        2. Write content to temp file
        3. Fsync temp file to disk
        4. Close temp file descriptor (required before os.replace on Windows)
        5. Replace target with temp file atomically (with retry on Windows)
        6. Fsync parent directory on Linux/macOS
        7. On any failure: cleanup temp file and re-raise

    Note:
        For cross-platform safety, content must be bytes. Callers must encode
        string content using the appropriate encoding before calling this function.
    """
    target_dir = os.path.dirname(target_path) or '.'
    fd = None
    tmp_path = None

    try:
        # Create temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix='.tmp_')

        # Write content and flush to disk
        os.write(fd, content)
        os.fsync(fd)

        # MUST close before os.replace on Windows
        os.close(fd)
        fd = None

        # Atomic replace with retry on Windows
        _replace_with_retry(tmp_path, target_path)

        # Fsync parent directory on Linux/macOS
        _fsync_parent_directory(target_path)

    except Exception:
        # Cleanup on failure
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        raise


def safe_rename(src: str, dst: str) -> bool:
    """Rename file safely with cross-filesystem fallback.

    Args:
        src: Source file path
        dst: Destination file path

    Returns:
        True if cross-filesystem fallback was used, False if normal rename

    Raises:
        OSError: If rename/copy fails
        PermissionError: If operation is not permitted

    Implementation:
        If source and destination are on the same filesystem, uses atomic
        os.replace with retry on Windows. If on different filesystems, falls
        back to copy + fsync + delete source.

    Note:
        This function is primarily for the rename tool (Story 10). The atomic_write
        function creates temp files in the target directory, so cross-filesystem
        fallback shouldn't be needed there.
    """
    # Check if same filesystem
    src_stat = os.stat(src)
    dst_dir = os.path.dirname(dst)
    dst_dir_stat = os.stat(dst_dir)

    if src_stat.st_dev == dst_dir_stat.st_dev:
        # Same filesystem - use atomic replace
        _replace_with_retry(src, dst)
        _fsync_parent_directory(dst)
        return False
    else:
        # Cross-filesystem - fallback to copy + delete
        shutil.copy2(src, dst)

        # Fsync destination file
        with open(dst, 'r+b') as f:
            os.fsync(f.fileno())

        _fsync_parent_directory(dst)

        # Delete source
        os.unlink(src)

        return True
