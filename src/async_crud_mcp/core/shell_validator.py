"""Shell command validation against configurable deny patterns.

Compiles regex patterns once at init for efficient per-command checking.
Normalizes commands before matching to prevent bypass via shell escape tricks
(backslash insertion, empty quote insertion, ANSI-C quoting, etc.).
"""

import re
from typing import List, Tuple


# Regex to strip bash escape tricks that don't change command semantics:
#   - backslash before a non-special char: c\at -> cat
#   - empty single quotes: ca''t -> cat
#   - empty double quotes: ca""t -> cat
_EMPTY_SINGLE_QUOTES = re.compile(r"''")
_EMPTY_DOUBLE_QUOTES = re.compile(r'""')
_BACKSLASH_ESCAPE = re.compile(r"\\(.)")

# ANSI-C $'...' quoting: $'\x63\x61\x74' -> cat
_ANSI_C_QUOTE = re.compile(r"\$'((?:[^'\\]|\\x[0-9a-fA-F]{2}|\\[0-7]{1,3}|\\[nrtabfv\\'])*)'")


def _decode_ansi_c(match: re.Match) -> str:
    """Decode $'...' ANSI-C quoted strings to their literal form."""
    content = match.group(1)
    # Decode \xNN hex escapes
    content = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), content)
    # Decode \NNN octal escapes
    content = re.sub(r"\\([0-7]{1,3})", lambda m: chr(int(m.group(1), 8)), content)
    # Decode common backslash escapes
    for esc, char in [("\\n", "\n"), ("\\t", "\t"), ("\\r", "\r"), ("\\'", "'"), ("\\\\", "\\")]:
        content = content.replace(esc, char)
    return content


def _normalize_command(command: str) -> str:
    """Normalize a shell command to defeat escape-based bypass tricks.

    Strips:
      - ANSI-C $'...' quoting: $'\\x63\\x61\\x74' -> cat
      - Empty single quotes: ca''t -> cat
      - Empty double quotes: ca""t -> cat
      - Backslash before any char: c\\at -> cat, r\\m -> rm

    This runs BEFORE deny-pattern matching so that obfuscated commands
    are matched against their effective form.
    """
    # Decode ANSI-C quoting first (before empty-quote stripping)
    normalized = _ANSI_C_QUOTE.sub(_decode_ansi_c, command)
    normalized = _EMPTY_SINGLE_QUOTES.sub("", normalized)
    normalized = _EMPTY_DOUBLE_QUOTES.sub("", normalized)
    normalized = _BACKSLASH_ESCAPE.sub(r"\1", normalized)
    return normalized


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

        The command is normalized before matching to prevent bypass via
        shell escape tricks (backslash insertion, empty quotes, etc.).

        Returns:
            (allowed, matched_pattern, reason) -- allowed=True means command is OK.
            If denied, matched_pattern is the regex that matched and reason is
            the human-readable explanation.
        """
        normalized = _normalize_command(command)
        # Check both raw and normalized forms
        for compiled, pattern, reason in self._compiled:
            if compiled.search(command) or compiled.search(normalized):
                return False, pattern, reason
        return True, "", ""

    @property
    def pattern_count(self) -> int:
        return len(self._compiled)
