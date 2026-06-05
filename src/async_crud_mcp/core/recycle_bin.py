"""Recycle bin for safe file deletion with manifest tracking.

Moves deleted files to a recycle directory instead of permanent removal,
enabling recovery via restore operations. Tracks all operations in a
JSONL manifest file with HMAC-SHA256 integrity signatures.
"""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


class RecycleBinError(Exception):
    """Raised when a recycle bin operation fails."""


@dataclass
class RecycleEntry:
    """Metadata for a recycled file."""

    recycle_name: str
    original_path: str
    deleted_hash: str
    timestamp: str
    reason: str
    size_bytes: int
    status: str = "recycled"
    signature: str = ""


@dataclass
class RestoreResult:
    """Result of a file restore operation."""

    restored_path: str
    original_path: str
    recycle_name: str
    timestamp: str


class RecycleBin:
    """Manages safe file deletion via a recycle bin directory.

    Files are moved to a timestamped location in the recycle directory
    and tracked in a JSONL manifest for later restore or cleanup.

    All public methods are async and protected by an internal asyncio.Lock
    to prevent manifest corruption under concurrent access.

    Manifest entries are signed with HMAC-SHA256 to detect tampering of
    the original_path or other fields before restore.
    """

    def __init__(
        self,
        project_recycle_dir: Path | None,
        global_recycle_dir: Path,
        enabled: bool = True,
        retention_days: int = 90,
        max_size_mb: int = 500,
        hmac_key: bytes = b"",
    ):
        self._project_recycle_dir = project_recycle_dir
        self._global_recycle_dir = global_recycle_dir
        self.enabled = enabled
        self.retention_days = retention_days
        self.max_size_mb = max_size_mb
        self._hmac_key = hmac_key
        self._lock = asyncio.Lock()

    @property
    def recycle_dir(self) -> Path:
        """Active recycle directory (project-local if set, else global)."""
        if self._project_recycle_dir is not None:
            return self._project_recycle_dir
        return self._global_recycle_dir

    @property
    def manifest_path(self) -> Path:
        """Path to the JSONL manifest file."""
        return self.recycle_dir / ".manifest.jsonl"

    def _compute_signature(self, entry: RecycleEntry) -> str:
        """Compute HMAC-SHA256 signature for a manifest entry.

        The canonical message includes the fields most critical for
        restore integrity: recycle_name, original_path, deleted_hash,
        and size_bytes.
        """
        msg = f"{entry.recycle_name}:{entry.original_path}:{entry.deleted_hash}:{entry.size_bytes}"
        return hmac.new(self._hmac_key, msg.encode(), hashlib.sha256).hexdigest()

    def _ensure_recycle_dir(self) -> None:
        """Create the recycle directory and .gitignore if needed."""
        self.recycle_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self.recycle_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Recycle bin contents\n*\n!.gitignore\n!.manifest.jsonl\n", encoding="utf-8")

    def _generate_recycle_name(self, original_path: Path) -> str:
        """Generate a unique timestamped name for the recycled file."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        basename = original_path.name
        candidate = f"{ts}_{basename}"

        # Handle name collisions with counter suffix
        counter = 1
        while (self.recycle_dir / candidate).exists():
            candidate = f"{ts}_{counter}_{basename}"
            counter += 1

        return candidate

    def _append_manifest(self, entry: RecycleEntry) -> None:
        """Append an entry to the JSONL manifest."""
        line = json.dumps(asdict(entry), ensure_ascii=False) + "\n"
        with open(self.manifest_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _read_manifest(self) -> list[dict]:
        """Read all entries from the JSONL manifest."""
        if not self.manifest_path.exists():
            return []
        entries = []
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    async def recycle(self, file_path: Path, deleted_hash: str, reason: str = "", timeout: float = 30.0) -> RecycleEntry:
        """Move a file to the recycle bin.

        Args:
            file_path: Absolute path of the file to recycle.
            deleted_hash: SHA-256 hash of the file at deletion time.
            reason: Optional human-readable reason for deletion.
            timeout: Lock acquisition timeout in seconds.

        Returns:
            RecycleEntry with restore metadata.

        Raises:
            RecycleBinError: If the recycle bin is disabled, the move fails,
                or the lock cannot be acquired within the timeout.
        """
        if not self.enabled:
            raise RecycleBinError("Recycle bin is disabled")

        if not file_path.exists():
            raise RecycleBinError(f"File not found: {file_path}")

        try:
            async with asyncio.timeout(timeout):
                async with self._lock:
                    self._ensure_recycle_dir()

                    size_bytes = file_path.stat().st_size
                    recycle_name = self._generate_recycle_name(file_path)
                    dest = self.recycle_dir / recycle_name
                    timestamp = datetime.now(timezone.utc).isoformat()

                    try:
                        shutil.move(str(file_path), str(dest))
                    except OSError as e:
                        raise RecycleBinError(f"Failed to move file to recycle bin: {e}") from e

                    entry = RecycleEntry(
                        recycle_name=recycle_name,
                        original_path=str(file_path),
                        deleted_hash=deleted_hash,
                        timestamp=timestamp,
                        reason=reason,
                        size_bytes=size_bytes,
                        status="recycled",
                    )

                    if self._hmac_key:
                        entry.signature = self._compute_signature(entry)

                    self._append_manifest(entry)

                    logger.debug("Recycled {} -> {}", file_path, dest)
                    return entry
        except TimeoutError:
            raise RecycleBinError(f"Recycle bin operation timed out after {timeout}s")

    async def restore(self, recycle_name: str, destination: Path | None = None, force: bool = False, timeout: float = 30.0, path_validator=None) -> RestoreResult:
        """Restore a file from the recycle bin.

        Args:
            recycle_name: Name of the file in the recycle directory.
            destination: Custom restore path. If None, restores to original location.
            force: Overwrite destination if it already exists.
            timeout: Lock acquisition timeout in seconds.
            path_validator: Optional PathValidator. When provided, the resolved
                restore target is validated against the allowed base directories
                before any filesystem change. The manifest original_path is
                untrusted (unsigned entries are permitted), so this prevents a
                tampered entry from restoring a file outside the project root.

        Returns:
            RestoreResult with the restored file path.

        Raises:
            RecycleBinError: If the file is not found, destination conflicts,
                integrity check fails, or the lock cannot be acquired.
        """
        try:
            async with asyncio.timeout(timeout):
                async with self._lock:
                    recycled_path = self.recycle_dir / recycle_name
                    if not recycled_path.exists():
                        raise RecycleBinError(f"Recycled file not found: {recycle_name}")

                    # Look up original path from manifest
                    original_path = None
                    entry_signature = ""
                    entry_data_match = None
                    for entry_data in self._read_manifest():
                        if entry_data.get("recycle_name") == recycle_name and entry_data.get("status") == "recycled":
                            original_path = entry_data.get("original_path")
                            entry_signature = entry_data.get("signature", "")
                            entry_data_match = entry_data
                            break

                    # Verify HMAC integrity if signature is present
                    if entry_data_match is not None and entry_signature:
                        verify_entry = RecycleEntry(
                            recycle_name=entry_data_match.get("recycle_name", ""),
                            original_path=entry_data_match.get("original_path", ""),
                            deleted_hash=entry_data_match.get("deleted_hash", ""),
                            timestamp=entry_data_match.get("timestamp", ""),
                            reason=entry_data_match.get("reason", ""),
                            size_bytes=entry_data_match.get("size_bytes", 0),
                        )
                        expected_sig = self._compute_signature(verify_entry)
                        if not hmac.compare_digest(entry_signature, expected_sig):
                            raise RecycleBinError(
                                "Integrity check failed: manifest entry has been tampered with"
                            )
                    elif entry_data_match is not None and not entry_signature:
                        logger.warning(
                            "Restoring unsigned manifest entry for {}: no HMAC signature present",
                            recycle_name,
                        )

                    if destination is not None:
                        restore_to = destination
                    elif original_path is not None:
                        restore_to = Path(original_path)
                    else:
                        raise RecycleBinError(
                            f"No original path found for {recycle_name} and no destination specified"
                        )

                    # Enforce path policy on the resolved restore target before
                    # any filesystem mutation. Guards against a tampered/unsigned
                    # manifest original_path pointing outside the allowed base
                    # directories (e.g. /etc/shadow, C:\\Windows\\System32).
                    if path_validator is not None:
                        try:
                            path_validator.validate_operation(str(restore_to), "write")
                        except Exception as e:
                            raise RecycleBinError(
                                f"Restore target failed path validation: {restore_to} ({e})"
                            ) from e

                    if restore_to.exists() and not force:
                        raise RecycleBinError(
                            f"Destination already exists: {restore_to}. Use force=True to overwrite."
                        )

                    # Guard: refuse to restore into recycle directory itself
                    if self.is_protected_path(restore_to):
                        raise RecycleBinError(
                            "Cannot restore into the recycle bin or config directory"
                        )

                    # Create parent directories if needed
                    restore_to.parent.mkdir(parents=True, exist_ok=True)

                    # Safe-recycle existing file before overwriting (force=True)
                    if restore_to.exists() and force:
                        try:
                            existing_size = restore_to.stat().st_size
                            if restore_to.is_file():
                                with open(restore_to, "rb") as ef:
                                    existing_hash = "sha256:" + hashlib.sha256(ef.read()).hexdigest()
                            else:
                                entry_count = len(list(restore_to.iterdir()))
                                existing_hash = f"dir:{entry_count}_entries"
                            existing_recycle_name = self._generate_recycle_name(restore_to)
                            existing_dest = self.recycle_dir / existing_recycle_name
                            shutil.move(str(restore_to), str(existing_dest))
                            existing_entry = RecycleEntry(
                                recycle_name=existing_recycle_name,
                                original_path=str(restore_to),
                                deleted_hash=existing_hash,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                reason="overwritten-by-restore",
                                size_bytes=existing_size,
                                status="recycled",
                            )
                            if self._hmac_key:
                                existing_entry.signature = self._compute_signature(existing_entry)
                            self._append_manifest(existing_entry)
                            logger.debug("Recycled existing {} before restore", restore_to)
                        except OSError as e:
                            raise RecycleBinError(
                                f"Failed to recycle existing file before restore: {e}"
                            ) from e

                    try:
                        shutil.move(str(recycled_path), str(restore_to))
                    except OSError as e:
                        raise RecycleBinError(f"Failed to restore file: {e}") from e

                    timestamp = datetime.now(timezone.utc).isoformat()

                    # Append RESTORED entry to manifest
                    restored_entry = RecycleEntry(
                        recycle_name=recycle_name,
                        original_path=original_path or str(restore_to),
                        deleted_hash="",
                        timestamp=timestamp,
                        reason="restored",
                        size_bytes=0,
                        status="restored",
                    )
                    self._append_manifest(restored_entry)

                    logger.debug("Restored {} -> {}", recycle_name, restore_to)
                    return RestoreResult(
                        restored_path=str(restore_to),
                        original_path=original_path or str(restore_to),
                        recycle_name=recycle_name,
                        timestamp=timestamp,
                    )
        except TimeoutError:
            raise RecycleBinError(f"Recycle bin operation timed out after {timeout}s")

    async def list_entries(self, limit: int = 50, timeout: float = 10.0) -> list[RecycleEntry]:
        """List recycled items, most recent first.

        Only returns entries with status="recycled" (not restored/cleaned).

        Args:
            limit: Maximum number of entries to return.
            timeout: Lock acquisition timeout in seconds.

        Returns:
            List of RecycleEntry objects, most recent first.

        Raises:
            RecycleBinError: If the lock cannot be acquired within the timeout.
        """
        try:
            async with asyncio.timeout(timeout):
                async with self._lock:
                    all_entries = self._read_manifest()

                    # Build set of restored/cleaned names
                    non_active = set()
                    for entry_data in all_entries:
                        if entry_data.get("status") in ("restored", "cleaned"):
                            non_active.add(entry_data.get("recycle_name"))

                    # Filter to active recycled entries
                    active = []
                    for entry_data in all_entries:
                        if (
                            entry_data.get("status") == "recycled"
                            and entry_data.get("recycle_name") not in non_active
                        ):
                            active.append(RecycleEntry(**{
                                k: entry_data.get(k, "")
                                for k in ("recycle_name", "original_path", "deleted_hash", "timestamp", "reason", "size_bytes", "status", "signature")
                            }))

                    # Sort by timestamp descending (most recent first)
                    active.sort(key=lambda e: e.timestamp, reverse=True)
                    return active[:limit]
        except TimeoutError:
            raise RecycleBinError(f"Recycle bin operation timed out after {timeout}s")

    async def cleanup(self, retention_days: int | None = None, timeout: float = 30.0) -> int:
        """Remove entries older than the retention period.

        Args:
            retention_days: Override retention period (uses instance default if None).
            timeout: Lock acquisition timeout in seconds.

        Returns:
            Number of entries removed.

        Raises:
            RecycleBinError: If the lock cannot be acquired within the timeout.
        """
        try:
            async with asyncio.timeout(timeout):
                async with self._lock:
                    days = retention_days if retention_days is not None else self.retention_days
                    cutoff = time.time() - (days * 86400)
                    removed = 0

                    all_entries = self._read_manifest()

                    # Build set of already restored names
                    restored_names = set()
                    for entry_data in all_entries:
                        if entry_data.get("status") in ("restored", "cleaned"):
                            restored_names.add(entry_data.get("recycle_name"))

                    for entry_data in all_entries:
                        if entry_data.get("status") != "recycled":
                            continue
                        recycle_name = entry_data.get("recycle_name", "")
                        if recycle_name in restored_names:
                            continue

                        ts_str = entry_data.get("timestamp", "")
                        try:
                            entry_time = datetime.fromisoformat(ts_str).timestamp()
                        except (ValueError, TypeError):
                            continue

                        if entry_time < cutoff:
                            recycled_path = self.recycle_dir / recycle_name
                            if recycled_path.exists():
                                try:
                                    if recycled_path.is_dir():
                                        shutil.rmtree(str(recycled_path))
                                    else:
                                        os.unlink(str(recycled_path))
                                except OSError:
                                    continue

                            # Append cleaned entry
                            cleaned = RecycleEntry(
                                recycle_name=recycle_name,
                                original_path=entry_data.get("original_path", ""),
                                deleted_hash="",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                reason="cleanup",
                                size_bytes=0,
                                status="cleaned",
                            )
                            self._append_manifest(cleaned)
                            removed += 1

                    return removed
        except TimeoutError:
            raise RecycleBinError(f"Recycle bin operation timed out after {timeout}s")

    def is_protected_path(self, path: Path) -> bool:
        """Check if path is inside or equal to the recycle directory.

        Args:
            path: Path to check.

        Returns:
            True if the path is inside or equal to the recycle directory.
        """
        try:
            resolved = path.resolve()
            recycle_resolved = self.recycle_dir.resolve()
            resolved.relative_to(recycle_resolved)
            return True
        except ValueError:
            return False

    def set_project_dir(self, project_recycle_dir: Path | None) -> None:
        """Update the project-local recycle directory.

        Called on project activation to switch recycle operations
        to a project-scoped directory.

        Args:
            project_recycle_dir: Project recycle directory, or None to use global.
        """
        self._project_recycle_dir = project_recycle_dir
