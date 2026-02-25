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


def find_mnemonic_spans(
    line: str,
    *,
    min_consecutive: int = 6,
) -> List[tuple]:
    """Find BIP-39 mnemonic sequence spans in a line.

    Returns (start, end) character offsets for each consecutive mnemonic
    sequence that meets the threshold. Uses the same detection logic as
    check_mnemonic_sequence but returns span positions instead of a bool.

    Args:
        line: Single line of text to check.
        min_consecutive: Minimum consecutive BIP-39 words to trigger.

    Returns:
        List of (start, end) tuples for each mnemonic span found.
    """
    bip39_words = _load_bip39_wordset()
    if not bip39_words:
        return []

    words = line.lower().split()
    if len(words) < min_consecutive:
        return []

    # Check function-word threshold
    line_words_set = set(words)
    has_function_words = bool(line_words_set & _ENGLISH_FUNCTION_WORDS)
    threshold = 12 if has_function_words else min_consecutive

    # Find word positions in the original line (case-insensitive matching)
    word_positions = []  # [(start, end, is_bip39), ...]
    search_start = 0
    for word in words:
        idx = line.lower().find(word, search_start)
        if idx == -1:
            break
        word_positions.append((idx, idx + len(word), word in bip39_words))
        search_start = idx + len(word)

    # Find runs of consecutive BIP-39 words
    spans = []
    run_start = None
    run_count = 0
    for i, (start, end, is_bip39) in enumerate(word_positions):
        if is_bip39:
            if run_start is None:
                run_start = i
            run_count += 1
        else:
            if run_count >= threshold and run_start is not None:
                span_start = word_positions[run_start][0]
                span_end = word_positions[i - 1][1]
                spans.append((span_start, span_end))
            run_start = None
            run_count = 0

    # Handle run that extends to end of line
    if run_count >= threshold and run_start is not None:
        span_start = word_positions[run_start][0]
        span_end = word_positions[-1][1]
        spans.append((span_start, span_end))

    return spans


@dataclass
class ContentScanResult:
    """Result of a content scan operation."""

    blocked: bool
    matched_pattern: Optional[str] = None
    matched_line: Optional[int] = None


@dataclass
class RedactionSpan:
    """A single redacted region in the content."""

    id: int                    # Sequential ID (1-based)
    rule_name: str             # e.g. "aws-access-key-id"
    line: int                  # 1-based line number
    col_start: int             # 0-based column offset in line
    col_end: int               # 0-based column end (exclusive)
    original_length: int       # Character count of redacted span


@dataclass
class RedactedContent:
    """Result of content redaction."""

    content: str               # Content with placeholders
    redactions: List[RedactionSpan]  # Metadata for each placeholder
    has_redactions: bool       # Convenience flag


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

    def redact(self, content: str, path: str) -> RedactedContent:
        """Redact sensitive spans in content with semantic placeholders.

        Scans line-by-line using the same allow-rule-first logic as scan().
        For non-allowed lines, finds ALL regex deny matches via finditer()
        and replaces each with ``<<REDACTED:rule_name:N>>``. BIP-39 mnemonic
        sequences are redacted as a single contiguous span.

        Matches are processed in reverse column order per line to avoid
        offset drift during replacement. Overlapping spans from different
        rules are resolved by keeping the higher-priority match.

        Args:
            content: Decoded file content to redact.
            path: File path (for future use, e.g. per-extension rules).

        Returns:
            RedactedContent with placeholders and metadata, or original
            content unchanged when nothing is sensitive.
        """
        if not self._enabled:
            return RedactedContent(content=content, redactions=[], has_redactions=False)

        has_deny_patterns = bool(self._deny_patterns)
        lines = content.splitlines(True)  # Keep line endings
        redaction_id = 0
        all_redactions: List[RedactionSpan] = []

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            # Strip trailing newline for matching (but preserve it in output)
            line_content = line.rstrip("\n").rstrip("\r")

            # Check allow patterns first
            allowed = False
            for pattern, _name in self._allow_patterns:
                if pattern.search(line_content):
                    allowed = True
                    break

            if allowed:
                continue

            # Collect all match spans on this line: (col_start, col_end, rule_name)
            spans: List[tuple] = []

            if has_deny_patterns:
                for pattern, name in self._deny_patterns:
                    for m in pattern.finditer(line_content):
                        spans.append((m.start(), m.end(), name))

            # BIP-39 mnemonic sequences
            for mstart, mend in find_mnemonic_spans(line_content):
                spans.append((mstart, mend, "crypto-mnemonic-sequence"))

            if not spans:
                continue

            # Sort by start position, then by length descending (longer match wins)
            spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

            # Merge overlapping spans into their union (longest match wins name)
            merged: List[tuple] = []
            for span in spans:
                if merged and span[0] < merged[-1][1]:
                    # Overlaps -- extend to cover both spans
                    prev = merged[-1]
                    prev_len = prev[1] - prev[0]
                    span_len = span[1] - span[0]
                    winner_name = span[2] if span_len > prev_len else prev[2]
                    merged[-1] = (prev[0], max(prev[1], span[1]), winner_name)
                    continue
                merged.append(span)

            # Assign IDs in forward order (left-to-right), build metadata
            line_redactions: List[tuple] = []  # (col_start, col_end, rule_name, id)
            for col_start, col_end, rule_name in merged:
                redaction_id += 1
                original_length = col_end - col_start
                all_redactions.append(RedactionSpan(
                    id=redaction_id,
                    rule_name=rule_name,
                    line=line_num,
                    col_start=col_start,
                    col_end=col_end,
                    original_length=original_length,
                ))
                line_redactions.append((col_start, col_end, rule_name, redaction_id))

            # Replace in reverse order to preserve offsets
            suffix = line[len(line_content):]
            for col_start, col_end, rule_name, rid in reversed(line_redactions):
                placeholder = f"<<REDACTED:{rule_name}:{rid}>>"
                line_content = line_content[:col_start] + placeholder + line_content[col_end:]

            lines[line_idx] = line_content + suffix

        return RedactedContent(
            content="".join(lines),
            redactions=all_redactions,
            has_redactions=len(all_redactions) > 0,
        )
