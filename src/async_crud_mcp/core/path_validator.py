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


class AccessDeniedError(PathValidationError):
    """Raised when a path is denied by an access policy rule."""
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

    def __init__(
        self,
        base_directories: Optional[List[str]] = None,
        access_rules: Optional[List] = None,
        default_destructive_policy: str = "allow",
    ):
        """Initialize validator with allowed base directories and access rules.

        Args:
            base_directories: List of directory paths to whitelist.
                Each is resolved to absolute and symlinks are followed.
            access_rules: List of PathRule objects for per-operation access control.
                Rules are evaluated in priority order (highest first, first-match-wins).
            default_destructive_policy: Fallback policy when no access rule matches.
                Either "allow" or "deny". Defaults to "allow" for backward compatibility.
        """
        self._base_directories = base_directories or []
        self._default_destructive_policy = default_destructive_policy

        # Pre-sort access rules by priority descending for first-match-wins evaluation
        self._access_rules = sorted(
            access_rules or [],
            key=lambda r: r.priority,
            reverse=True,
        )

        # Resolve and normalize base directories at init time
        self._resolved_bases: List[str] = []
        for base_dir in self._base_directories:
            resolved = os.path.realpath(os.path.expanduser(base_dir))
            normalized = os.path.normpath(resolved)
            # Apply case normalization for Windows
            normalized = os.path.normcase(normalized)
            self._resolved_bases.append(normalized)

        # Pre-resolve access rule paths for efficient matching
        self._resolved_rules: List[tuple] = []
        for rule in self._access_rules:
            rule_path = rule.path
            if not os.path.isabs(rule_path):
                rule_path = os.path.join(os.getcwd(), rule_path)
            resolved = os.path.realpath(os.path.expanduser(rule_path))
            normalized = os.path.normcase(os.path.normpath(resolved))
            self._resolved_rules.append((normalized, rule))

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

    def validate_operation(self, path: str, op_type: str) -> Path:
        """Validate a path for a specific operation type against access rules.

        First checks base directory containment via validate(), then evaluates
        access rules in priority order (first-match-wins). Read operations are
        not subject to access rules.

        Args:
            path: Path to validate (can be relative or absolute)
            op_type: Operation type ("write", "update", "delete", "rename")

        Returns:
            Validated Path object (absolute, resolved)

        Raises:
            PathValidationError: If path is outside allowed base directories
            AccessDeniedError: If an access rule denies the operation
        """
        # Step 1: Base directory validation (unchanged behavior)
        validated = self.validate(path)

        # Step 2: If no access rules configured, skip rule evaluation
        if not self._resolved_rules:
            if self._default_destructive_policy == "deny":
                raise AccessDeniedError(
                    f"Operation '{op_type}' denied on {path}: "
                    f"no access rules configured and default policy is 'deny'"
                )
            return validated

        # Step 3: Normalize the validated path for rule matching
        normalized = os.path.normcase(os.path.normpath(str(validated)))

        # Step 4: Evaluate rules in priority order (first match wins)
        for rule_path, rule in self._resolved_rules:
            # Check if operation type matches this rule
            if "*" not in rule.operations and op_type not in rule.operations:
                continue

            # Check if path matches this rule (prefix match)
            rule_with_sep = rule_path if rule_path.endswith(os.sep) else rule_path + os.sep
            normalized_with_sep = normalized if normalized.endswith(os.sep) else normalized + os.sep

            if normalized == rule_path or normalized_with_sep.startswith(rule_with_sep):
                if rule.action == "deny":
                    raise AccessDeniedError(
                        f"Operation '{op_type}' denied on {path}: "
                        f"blocked by access rule for '{rule.path}'"
                    )
                return validated

        # Step 5: No rule matched, apply default policy
        if self._default_destructive_policy == "deny":
            raise AccessDeniedError(
                f"Operation '{op_type}' denied on {path}: "
                f"no matching access rule and default policy is 'deny'"
            )
        return validated
