"""Tests for ContentScanner sensitive data detection."""

import pytest

from async_crud_mcp.config import ContentRule
from async_crud_mcp.core.content_scanner import ContentScanner, ContentScanResult


class TestContentScannerBasic:
    """Test basic scanning behavior."""

    def _make_rule(self, name, pattern, action="deny", priority=0):
        return ContentRule(name=name, pattern=pattern, action=action, priority=priority)

    def test_no_rules_passes_all_content(self):
        """Scanner with no rules passes all content through."""
        scanner = ContentScanner(rules=[], enabled=True)
        result = scanner.scan("AWS_SECRET_ACCESS_KEY=abcdef123456", "/tmp/file.txt")
        assert not result.blocked

    def test_disabled_scanner_passes_all_content(self):
        """Disabled scanner passes all content through."""
        rules = [self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+")]
        scanner = ContentScanner(rules=rules, enabled=False)
        result = scanner.scan("AWS_SECRET_ACCESS_KEY=abcdef123456", "/tmp/file.txt")
        assert not result.blocked

    def test_deny_rule_blocks_matching_content(self):
        """A deny rule blocks content that matches the pattern."""
        rules = [self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+")]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "some config\nAWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE\nmore stuff"
        result = scanner.scan(content, "/tmp/config.txt")

        assert result.blocked
        assert result.matched_pattern == "aws_key"
        assert result.matched_line == 2

    def test_deny_rule_passes_non_matching_content(self):
        """A deny rule does not block content that doesn't match."""
        rules = [self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+")]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "just some normal text\nno secrets here\n"
        result = scanner.scan(content, "/tmp/clean.txt")

        assert not result.blocked
        assert result.matched_pattern is None
        assert result.matched_line is None


class TestContentScannerPatterns:
    """Test specific sensitive data patterns."""

    def _make_rule(self, name, pattern, action="deny", priority=0):
        return ContentRule(name=name, pattern=pattern, action=action, priority=priority)

    def test_private_key_header_detected(self):
        """Private key header pattern is detected."""
        rules = [self._make_rule("private_key", r"-----BEGIN.*PRIVATE KEY-----")]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIBogI..."
        result = scanner.scan(content, "/tmp/key.pem")

        assert result.blocked
        assert result.matched_pattern == "private_key"
        assert result.matched_line == 1

    def test_generic_api_key_detected(self):
        """Generic API key pattern is detected."""
        rules = [
            self._make_rule(
                "api_key",
                r"(?i)(api[_-]?key|api[_-]?secret)\s*[=:]\s*['\"]?[A-Za-z0-9+/=_-]{20,}",
            )
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = 'api_key = "FAKE_KEY_abcdefghijklmnopqrstuvwxyz"'
        result = scanner.scan(content, "/tmp/config.yaml")

        assert result.blocked
        assert result.matched_pattern == "api_key"

    def test_password_assignment_detected(self):
        """Password assignment pattern is detected."""
        rules = [
            self._make_rule(
                "password",
                r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"]?\S{8,}",
            )
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = 'database:\n  password: "supersecretpass123"\n'
        result = scanner.scan(content, "/tmp/db.yml")

        assert result.blocked
        assert result.matched_pattern == "password"
        assert result.matched_line == 2


class TestContentScannerAllowOverride:
    """Test allow rules exempting content from deny rules."""

    def _make_rule(self, name, pattern, action="deny", priority=0):
        return ContentRule(name=name, pattern=pattern, action=action, priority=priority)

    def test_allow_rule_exempts_matching_line(self):
        """An allow rule for a line prevents deny rules from blocking it."""
        rules = [
            self._make_rule("test_ok", "DUMMY_KEY_FOR_TESTING", action="allow", priority=200),
            self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+", priority=100),
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "AWS_SECRET_ACCESS_KEY=DUMMY_KEY_FOR_TESTING"
        result = scanner.scan(content, "/tmp/test_fixtures.py")

        assert not result.blocked

    def test_allow_only_exempts_matched_lines(self):
        """Allow rule only exempts lines it matches, not all lines."""
        rules = [
            self._make_rule("test_ok", "DUMMY_KEY_FOR_TESTING", action="allow", priority=200),
            self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+", priority=100),
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = (
            "AWS_SECRET_ACCESS_KEY=DUMMY_KEY_FOR_TESTING\n"  # allowed
            "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7REAL\n"  # NOT allowed
        )
        result = scanner.scan(content, "/tmp/mixed.txt")

        assert result.blocked
        assert result.matched_pattern == "aws_key"
        assert result.matched_line == 2

    def test_allow_rule_alone_does_not_block(self):
        """Allow rules alone (no deny rules) never block content."""
        rules = [
            self._make_rule("test_ok", "DUMMY_KEY_FOR_TESTING", action="allow", priority=200),
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "some random content\nAWS_SECRET_ACCESS_KEY=realkey123456789012"
        result = scanner.scan(content, "/tmp/file.txt")

        assert not result.blocked


class TestContentScannerEdgeCases:
    """Test edge cases and boundary conditions."""

    def _make_rule(self, name, pattern, action="deny", priority=0):
        return ContentRule(name=name, pattern=pattern, action=action, priority=priority)

    def test_empty_content(self):
        """Empty content passes scanning."""
        rules = [self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+")]
        scanner = ContentScanner(rules=rules, enabled=True)
        result = scanner.scan("", "/tmp/empty.txt")

        assert not result.blocked

    def test_single_line_content(self):
        """Single line content without newline is scanned correctly."""
        rules = [self._make_rule("aws_key", r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+")]
        scanner = ContentScanner(rules=rules, enabled=True)
        result = scanner.scan("AWS_SECRET_ACCESS_KEY=secret", "/tmp/file.txt")

        assert result.blocked
        assert result.matched_line == 1

    def test_line_number_accuracy(self):
        """Line numbers in scan results are 1-based and accurate."""
        rules = [self._make_rule("secret", r"SECRET")]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "line 1\nline 2\nline 3 SECRET\nline 4"
        result = scanner.scan(content, "/tmp/file.txt")

        assert result.blocked
        assert result.matched_line == 3

    def test_multiple_deny_rules_first_match_wins(self):
        """With multiple deny rules, first matching line triggers."""
        rules = [
            self._make_rule("rule_a", r"PATTERN_A", priority=100),
            self._make_rule("rule_b", r"PATTERN_B", priority=50),
        ]
        scanner = ContentScanner(rules=rules, enabled=True)
        content = "PATTERN_B on line 1\nPATTERN_A on line 2"
        result = scanner.scan(content, "/tmp/file.txt")

        # Line 1 matches rule_b (priority 50) - but rule_a (priority 100) is checked
        # first per line. Line 1 doesn't match rule_a, but matches rule_b.
        assert result.blocked
        assert result.matched_line == 1
        assert result.matched_pattern == "rule_b"

    def test_scan_result_dataclass(self):
        """ContentScanResult has correct default values."""
        result = ContentScanResult(blocked=False)
        assert not result.blocked
        assert result.matched_pattern is None
        assert result.matched_line is None

    def test_content_with_only_newlines(self):
        """Content with only newlines passes scanning."""
        rules = [self._make_rule("secret", r"SECRET")]
        scanner = ContentScanner(rules=rules, enabled=True)
        result = scanner.scan("\n\n\n", "/tmp/file.txt")

        assert not result.blocked
