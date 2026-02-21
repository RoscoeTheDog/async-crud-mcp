"""Content scanning for sensitive data detection in file reads.

Provides a post-read filter that scans decoded file content against configurable
regex patterns. Matching content is blocked before it reaches the agent.
"""

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ContentScanResult:
    """Result of a content scan operation."""

    blocked: bool
    matched_pattern: Optional[str] = None
    matched_line: Optional[int] = None


class ContentScanner:
    """Scans file content against configurable regex patterns.

    Rules are evaluated per-line in priority order (highest first).
    Allow rules take precedence when they match, letting content through
    even if a deny rule would also match. If no allow rule matches and
    a deny rule matches, the content is blocked.

    Args:
        rules: List of ContentRule objects (from config).
        enabled: Whether scanning is active. When False, all content passes.
    """

    def __init__(self, rules: List, enabled: bool = True):
        self._enabled = enabled

        # Sort rules by priority descending (highest first)
        sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)

        # Pre-compile regexes and separate allow/deny for efficient evaluation
        self._allow_patterns: List[tuple] = []  # (compiled_regex, name)
        self._deny_patterns: List[tuple] = []   # (compiled_regex, name)

        for rule in sorted_rules:
            compiled = re.compile(rule.pattern)
            entry = (compiled, rule.name)
            if rule.action == "allow":
                self._allow_patterns.append(entry)
            else:
                self._deny_patterns.append(entry)

    def scan(self, content: str, path: str) -> ContentScanResult:
        """Scan content for sensitive patterns.

        Scans line-by-line for efficiency and short-circuits on first deny match.
        Allow patterns are checked first per line; if an allow pattern matches
        a line, deny patterns are skipped for that line.

        Args:
            content: Decoded file content to scan.
            path: File path (for future use, e.g. per-extension rules).

        Returns:
            ContentScanResult with blocked=True if a deny pattern matched,
            or blocked=False if content is clean.
        """
        if not self._enabled or not self._deny_patterns:
            return ContentScanResult(blocked=False)

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Check allow patterns first - if any match this line, skip deny checks
            allowed = False
            for pattern, _name in self._allow_patterns:
                if pattern.search(line):
                    allowed = True
                    break

            if allowed:
                continue

            # Check deny patterns
            for pattern, name in self._deny_patterns:
                if pattern.search(line):
                    return ContentScanResult(
                        blocked=True,
                        matched_pattern=name,
                        matched_line=line_num,
                    )

        return ContentScanResult(blocked=False)
