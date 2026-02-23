"""Content scanning for sensitive data detection in file reads.

Provides a post-read filter that scans decoded file content against configurable
regex patterns and programmatic checks. Matching content is blocked before it
reaches the agent.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional


# English function words that appear in normal prose but NOT in the BIP-39
# wordlist. Used to distinguish mnemonic phrases from natural English text.
# Words that overlap with BIP-39 (above, also, before, below, between, can,
# during, else, have, into, just, must, only, that, then, they, this, under,
# until, upon, very, what, when, where, will, you) are excluded so they
# don't cause false negatives on real mnemonic phrases.
_ENGLISH_FUNCTION_WORDS = frozenset({
    "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
    "has", "had", "do", "does", "did", "would", "shall",
    "should", "may", "might", "could",
    "i", "me", "my", "mine", "we", "us", "our", "ours",
    "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "them", "their", "theirs",
    "these", "those",
    "of", "in", "to", "for", "with", "on", "at", "from", "by", "as",
    "through", "after", "along",
    "and", "but", "or", "nor", "not", "no", "so", "yet",
    "if", "while", "how",
    "which", "who", "whom", "whose", "than", "whether",
    "too",
})


@lru_cache(maxsize=1)
def _load_bip39_wordset() -> frozenset:
    """Load the BIP-39 English wordlist as a frozen set for O(1) lookups.

    Uses the trezor/python-mnemonic package which ships with the official
    2048-word English wordlist. Falls back to an empty set if unavailable.
    """
    try:
        from mnemonic import Mnemonic
        m = Mnemonic("english")
        return frozenset(m.wordlist)
    except Exception:
        return frozenset()


def check_mnemonic_sequence(
    line: str,
    *,
    min_consecutive: int = 6,
) -> bool:
    """Check if a line contains a BIP-39 mnemonic sequence.

    Detects sequences of consecutive words that are all in the BIP-39
    English wordlist, then cross-checks against common English function
    words to reduce false positives. Normal English text contains function
    words (the, is, of, to, and, etc.) which are absent from the BIP-39
    wordlist, so their presence on a line indicates natural language.

    Args:
        line: Single line of text to check.
        min_consecutive: Minimum consecutive BIP-39 words to trigger (default 6).

    Returns:
        True if the line likely contains a mnemonic phrase.
    """
    bip39_words = _load_bip39_wordset()
    if not bip39_words:
        return False

    words = line.lower().split()
    if len(words) < min_consecutive:
        return False

    # Check if any function words are present on this line.
    # Normal English text almost always contains function words;
    # mnemonic phrases never do (none are in BIP-39).
    line_words_set = set(words)
    has_function_words = bool(line_words_set & _ENGLISH_FUNCTION_WORDS)

    # Count longest run of consecutive BIP-39 words
    consecutive = 0
    max_consecutive = 0
    for word in words:
        if word in bip39_words:
            consecutive += 1
            if consecutive > max_consecutive:
                max_consecutive = consecutive
        else:
            consecutive = 0

    if max_consecutive < min_consecutive:
        return False

    # If function words are present, require a much longer sequence
    # to flag (12+ words = minimum valid mnemonic length).
    # This handles edge cases like "you can abandon all hope" where
    # a few BIP-39 words appear alongside function words.
    if has_function_words:
        return max_consecutive >= 12

    return True


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

    In addition to regex rules, the scanner runs programmatic checks
    for patterns that cannot be expressed as simple regexes (e.g.,
    BIP-39 mnemonic phrase detection).

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

        After regex checks, programmatic checks (BIP-39 mnemonic detection)
        are run on lines not exempted by allow rules.

        Args:
            content: Decoded file content to scan.
            path: File path (for future use, e.g. per-extension rules).

        Returns:
            ContentScanResult with blocked=True if a deny pattern matched,
            or blocked=False if content is clean.
        """
        if not self._enabled:
            return ContentScanResult(blocked=False)

        has_deny_patterns = bool(self._deny_patterns)

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Check allow patterns first - if any match this line, skip deny checks
            allowed = False
            for pattern, _name in self._allow_patterns:
                if pattern.search(line):
                    allowed = True
                    break

            if allowed:
                continue

            # Check regex deny patterns
            if has_deny_patterns:
                for pattern, name in self._deny_patterns:
                    if pattern.search(line):
                        return ContentScanResult(
                            blocked=True,
                            matched_pattern=name,
                            matched_line=line_num,
                        )

            # Programmatic check: BIP-39 mnemonic sequences
            if check_mnemonic_sequence(line):
                return ContentScanResult(
                    blocked=True,
                    matched_pattern="crypto-mnemonic-sequence",
                    matched_line=line_num,
                )

        return ContentScanResult(blocked=False)
