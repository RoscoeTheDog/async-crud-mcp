"""Core functionality package."""

from .diff_engine import check_patch_applicability, compute_diff, compute_json_diff, compute_unified_diff
from .lock_manager import LockManager, LockTimeout, LockType
from .path_validator import PathValidationError, PathValidator

__all__ = [
    "LockManager",
    "LockTimeout",
    "LockType",
    "PathValidationError",
    "PathValidator",
    "compute_diff",
    "compute_json_diff",
    "compute_unified_diff",
    "check_patch_applicability",
]
