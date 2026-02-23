"""Recycle bin for safe file deletion with manifest tracking.

Moves deleted files to a recycle directory instead of permanent removal,
enabling recovery via restore operations. Tracks all operations in a
JSONL manifest file.
"""

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
    """

    def __init__(
        self,
        project_recycle_dir: Path | None,
        global_recycle_dir: Path,
        enabled: bool = True,
        retention_days: int = 90,
        max_size_mb: int = 500,
    ):
        self._project_recycle_dir = project_recycle_dir
        self._global_recycle_dir = global_recycle_dir
        self.enabled = enabled
        self.retention_days = retention_days
        self.max_size_mb = max_size_mb

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

    def recycle(self, file_path: Path, deleted_hash: str, reason: str = "") -> RecycleEntry:
        """Move a file to the recycle bin.

        Args:
            file_path: Absolute path of the file to recycle.
            deleted_hash: SHA-256 hash of the file at deletion time.
            reason: Optional human-readable reason for deletion.

        Returns:
            RecycleEntry with restore metadata.

        Raises:
            RecycleBinError: If the recycle bin is disabled or the move fails.
        """
        if not self.enabled:
            raise RecycleBinError("Recycle bin is disabled")

        if not file_path.exists():
            raise RecycleBinError(f"File not found: {file_path}")

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
        self._append_manifest(entry)

        logger.debug("Recycled {} -> {}", file_path, dest)
        return entry

    def restore(self, recycle_name: str, destination: Path | None = None, force: bool = False) -> RestoreResult:
        """Restore a file from the recycle bin.

        Args:
            recycle_name: Name of the file in the recycle directory.
            destination: Custom restore path. If None, restores to original location.
            force: Overwrite destination if it already exists.

        Returns:
            RestoreResult with the restored file path.

        Raises:
            RecycleBinError: If the file is not found or destination conflicts.
        """
        recycled_path = self.recycle_dir / recycle_name
        if not recycled_path.exists():
            raise RecycleBinError(f"Recycled file not found: {recycle_name}")

        # Look up original path from manifest
        original_path = None
        for entry_data in self._read_manifest():
            if entry_data.get("recycle_name") == recycle_name and entry_data.get("status") == "recycled":
                original_path = entry_data.get("original_path")
                break

        if destination is not None:
            restore_to = destination
        elif original_path is not None:
            restore_to = Path(original_path)
        else:
            raise RecycleBinError(
                f"No original path found for {recycle_name} and no destination specified"
            )

        if restore_to.exists() and not force:
            raise RecycleBinError(
                f"Destination already exists: {restore_to}. Use force=True to overwrite."
            )

        # Create parent directories if needed
        restore_to.parent.mkdir(parents=True, exist_ok=True)

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

    def list_entries(self, limit: int = 50) -> list[RecycleEntry]:
        """List recycled items, most recent first.

        Only returns entries with status="recycled" (not restored/cleaned).

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of RecycleEntry objects, most recent first.
        """
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
                    for k in ("recycle_name", "original_path", "deleted_hash", "timestamp", "reason", "size_bytes", "status")
                }))

        # Sort by timestamp descending (most recent first)
        active.sort(key=lambda e: e.timestamp, reverse=True)
        return active[:limit]

    def cleanup(self, retention_days: int | None = None) -> int:
        """Remove entries older than the retention period.

        Args:
            retention_days: Override retention period (uses instance default if None).

        Returns:
            Number of entries removed.
        """
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

    def set_project_dir(self, project_recycle_dir: Path | None) -> None:
        """Update the project-local recycle directory.

        Called on project activation to switch recycle operations
        to a project-scoped directory.

        Args:
            project_recycle_dir: Project recycle directory, or None to use global.
        """
        self._project_recycle_dir = project_recycle_dir
