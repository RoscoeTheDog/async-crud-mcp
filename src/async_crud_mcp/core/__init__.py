"""Core functionality package."""

from .audit_logger import AuditEntry, AuditLogger
from .background_tasks import BackgroundTask, BackgroundTaskRegistry
from .content_scanner import ContentScanner, ContentScanResult, RedactedContent, RedactionSpan
from .diff_engine import check_patch_applicability, compute_diff, compute_json_diff, compute_unified_diff
from .file_io import HashRegistry, atomic_write, compute_file_hash, compute_hash, safe_rename
from .lock_manager import LockManager, LockTimeout, LockType
from .path_validator import AccessDeniedError, PathValidationError, PathValidator
from .persistence import StatePersistence
from .recycle_bin import RecycleBin, RecycleBinError, RecycleEntry, RestoreResult
from . import process_guard
from .shell_provider import ShellNotFoundError, ShellProvider
from .shell_validator import ShellValidator
from .transaction_manager import (
    EditTransaction,
    StagedMatch,
    TransactionManager,
    apply_spans,
    make_anchor,
    rebase_match,
    spans_overlap,
)

__all__ = [
    "AccessDeniedError",
    "AuditEntry",
    "AuditLogger",
    "BackgroundTask",
    "BackgroundTaskRegistry",
    "ContentScanner",
    "ContentScanResult",
    "RedactedContent",
    "RedactionSpan",
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
    "process_guard",
    "RecycleBin",
    "RecycleBinError",
    "RecycleEntry",
    "RestoreResult",
    "TransactionManager",
    "EditTransaction",
    "StagedMatch",
    "make_anchor",
    "rebase_match",
    "apply_spans",
    "spans_overlap",
]
