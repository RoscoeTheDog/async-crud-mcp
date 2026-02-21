"""Core functionality package."""

from .audit_logger import AuditEntry, AuditLogger
from .background_tasks import BackgroundTask, BackgroundTaskRegistry
from .content_scanner import ContentScanner, ContentScanResult
from .diff_engine import check_patch_applicability, compute_diff, compute_json_diff, compute_unified_diff
from .file_io import HashRegistry, atomic_write, compute_file_hash, compute_hash, safe_rename
from .file_watcher import FileWatcher
from .lock_manager import LockManager, LockTimeout, LockType
from .path_validator import AccessDeniedError, PathValidationError, PathValidator
from .persistence import StatePersistence
from .shell_provider import ShellNotFoundError, ShellProvider
from .shell_validator import ShellValidator

__all__ = [
    "AccessDeniedError",
    "AuditEntry",
    "AuditLogger",
    "BackgroundTask",
    "BackgroundTaskRegistry",
    "ContentScanner",
    "ContentScanResult",
    "LockManager",
    "LockTimeout",
    "LockType",
    "PathValidationError",
    "PathValidator",
    "ShellNotFoundError",
    "ShellProvider",
    "ShellValidator",
    "compute_diff",
    "compute_json_diff",
    "compute_unified_diff",
    "check_patch_applicability",
    "atomic_write",
    "compute_hash",
    "compute_file_hash",
    "HashRegistry",
    "safe_rename",
    "StatePersistence",
    "FileWatcher",
]
