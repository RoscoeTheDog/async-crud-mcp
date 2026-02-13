"""Path validation with base directory whitelisting and security checks.

This module provides cross-platform path validation to prevent directory traversal
and unauthorized file access. All paths are resolved to their real filesystem
locations (following symlinks) before validation.
"""

import os
from pathlib import Path
from typing import List, Optional


class PathValidationError(Exception):
    """Raised when a path fails validation checks."""
    pass


class PathValidator:
    """Validates file paths against a whitelist of base directories.

    The validator enforces security by:
    - Resolving all paths to absolute
    - Following symlinks to real filesystem locations
    - Normalizing paths for cross-platform comparison
    - Rejecting paths outside whitelisted base directories
    - Handling Windows case-insensitivity and UNC paths

    Args:
        base_directories: List of allowed base directory paths. If empty,
            all paths are allowed (no restriction).

    Example:
        validator = PathValidator(['/var/data', '/tmp/uploads'])
        safe_path = validator.validate('/var/data/file.txt')  # OK
        validator.validate('/etc/passwd')  # Raises PathValidationError
    """

    def __init__(self, base_directories: Optional[List[str]] = None):
        """Initialize validator with allowed base directories.

        Args:
            base_directories: List of directory paths to whitelist.
                Each is resolved to absolute and symlinks are followed.
        """
        self._base_directories = base_directories or []

        # Resolve and normalize base directories at init time
        self._resolved_bases: List[str] = []
        for base_dir in self._base_directories:
            resolved = os.path.realpath(os.path.expanduser(base_dir))
            normalized = os.path.normpath(resolved)
            # Apply case normalization for Windows
            normalized = os.path.normcase(normalized)
            self._resolved_bases.append(normalized)

    def validate(self, path: str) -> Path:
        """Validate a path against the base directory whitelist.

        The path is resolved to absolute, symlinks are followed, and the
        result is checked against allowed base directories. On Windows,
        comparison is case-insensitive.

        Args:
            path: Path to validate (can be relative or absolute)

        Returns:
            Validated Path object (absolute, resolved)

        Raises:
            PathValidationError: If path is outside allowed directories
                or contains invalid components
        """
        # Handle empty path
        if not path:
            raise PathValidationError("Empty path string is not allowed")

        # Expand user home directory if present
        expanded = os.path.expanduser(path)

        # Convert to absolute path
        absolute = os.path.abspath(expanded)

        # Resolve symlinks to real filesystem location
        # This is the critical security step - we validate the REAL location
        resolved = os.path.realpath(absolute)

        # Normalize path separators and remove redundant components
        normalized = os.path.normpath(resolved)

        # Apply case normalization for Windows
        normalized = os.path.normcase(normalized)

        # Defense in depth: verify no .. components remain after normalization
        # (normpath should have removed them, but we verify)
        if '..' in Path(normalized).parts:
            raise PathValidationError(
                f"Path contains parent directory references after normalization: {path}"
            )

        # If no base directories configured, allow all paths
        if not self._resolved_bases:
            return Path(resolved)

        # Check if normalized path starts with any allowed base directory
        for base in self._resolved_bases:
            # Ensure base ends with separator for accurate prefix matching
            # This prevents /foo/bar from matching /foo/barbaz
            base_with_sep = base if base.endswith(os.sep) else base + os.sep
            normalized_with_sep = normalized if normalized.endswith(os.sep) else normalized + os.sep

            # Check if path equals base directory exactly
            if normalized == base:
                return Path(resolved)

            # Check if path is under base directory
            if normalized_with_sep.startswith(base_with_sep):
                return Path(resolved)

        # Path is outside all allowed base directories
        raise PathValidationError(
            f"Path is outside allowed base directories: {path} "
            f"(resolved to {resolved})"
        )

    @property
    def base_directories(self) -> List[str]:
        """Get the list of configured base directories (original paths)."""
        return self._base_directories.copy()

    @property
    def resolved_base_directories(self) -> List[str]:
        """Get the resolved and normalized base directories used for validation."""
        return self._resolved_bases.copy()
