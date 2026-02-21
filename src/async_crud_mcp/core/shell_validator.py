"""Shell command validation against configurable deny patterns.

Compiles regex patterns once at init for efficient per-command checking.
"""

import re
from typing import List, Tuple


class ShellValidator:
    """Validates shell commands against a deny list of regex patterns.

    Args:
        deny_patterns: List of ShellDenyPattern objects from config.
    """

    def __init__(self, deny_patterns: List) -> None:
        self._compiled: List[Tuple[re.Pattern, str, str]] = []
        self._compile(deny_patterns)

    def _compile(self, deny_patterns: List) -> None:
        self._compiled = []
        for dp in deny_patterns:
            try:
                compiled = re.compile(dp.pattern)
                self._compiled.append((compiled, dp.pattern, dp.reason))
            except re.error:
                pass  # Skip invalid patterns silently

    def reload(self, deny_patterns: List) -> None:
        """Recompile patterns (used on config hot-reload)."""
        self._compile(deny_patterns)

    def validate(self, command: str) -> tuple[bool, str, str]:
        """Check command against deny patterns.

        Returns:
            (allowed, matched_pattern, reason) -- allowed=True means command is OK.
            If denied, matched_pattern is the regex that matched and reason is
            the human-readable explanation.
        """
        for compiled, pattern, reason in self._compiled:
            if compiled.search(command):
                return False, pattern, reason
        return True, "", ""

    @property
    def pattern_count(self) -> int:
        return len(self._compiled)
