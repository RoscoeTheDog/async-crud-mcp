"""Unit tests for audit logger module."""

import json
from unittest.mock import patch

from async_crud_mcp.core.audit_logger import AuditConfig, AuditEntry, AuditLogger


def _make_entry(**overrides) -> AuditEntry:
    """Create an AuditEntry with sensible defaults."""
    defaults = {
        "timestamp": "2026-02-20T15:30:00+00:00",
        "session_id": "test-session-1",
        "client_id": "test-client",
        "request_id": "req-001",
        "project_root": None,
        "tool_name": "async_read_tool",
        "args_summary": {"path": "/tmp/test.txt"},
        "result_status": "ok",
        "result_code": None,
        "duration_ms": 42,
        "details": None,
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


class TestAuditEntry:
    """Test the AuditEntry dataclass."""

    def test_default_values(self):
        entry = AuditEntry(
            timestamp="2026-01-01T00:00:00Z",
            session_id="s1",
            client_id=None,
            request_id="r1",
            project_root=None,
            tool_name="test_tool",
        )
        assert entry.args_summary == {}
        assert entry.result_status == "unknown"
        assert entry.result_code is None
        assert entry.duration_ms == 0
        assert entry.details is None

    def test_full_entry(self):
        entry = _make_entry(details={"exit_code": 0})
        assert entry.tool_name == "async_read_tool"
        assert entry.details == {"exit_code": 0}
        assert entry.duration_ms == 42


class TestAuditLogger:
    """Test the AuditLogger class."""

    def test_writes_global_jsonl(self, tmp_path):
        """Verify entries are written to global audit.jsonl."""
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry()
        al.log(entry)

        jsonl = tmp_path / "audit.jsonl"
        assert jsonl.exists()
        lines = jsonl.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool_name"] == "async_read_tool"
        assert data["session_id"] == "test-session-1"
        assert data["duration_ms"] == 42

    def test_writes_project_jsonl(self, tmp_path):
        """Verify entries are written to per-project audit.jsonl."""
        global_dir = tmp_path / "global"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config = AuditConfig(log_to_global=False)
        al = AuditLogger(global_log_dir=global_dir, config=config)

        entry = _make_entry(project_root=str(project_dir))
        al.log(entry, project_root=project_dir)

        project_jsonl = project_dir / ".async-crud-mcp" / "logs" / "audit.jsonl"
        assert project_jsonl.exists()
        data = json.loads(project_jsonl.read_text(encoding="utf-8").strip())
        assert data["tool_name"] == "async_read_tool"

        # Global should NOT exist
        assert not (global_dir / "audit.jsonl").exists()

    def test_dual_write(self, tmp_path):
        """Verify entries written to both global and project."""
        global_dir = tmp_path / "global"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config = AuditConfig()
        al = AuditLogger(global_log_dir=global_dir, config=config)

        entry = _make_entry(project_root=str(project_dir))
        al.log(entry, project_root=project_dir)

        assert (global_dir / "audit.jsonl").exists()
        assert (project_dir / ".async-crud-mcp" / "logs" / "audit.jsonl").exists()

    def test_disabled_writes_nothing(self, tmp_path):
        """Verify disabled config writes nothing."""
        config = AuditConfig(enabled=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry()
        al.log(entry)

        assert not (tmp_path / "audit.jsonl").exists()

    def test_oserror_swallowed(self, tmp_path):
        """Verify OSError in file write is swallowed by _append."""
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry()
        # Patch builtins.open to raise inside _append's try/except
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise
            al.log(entry)

    def test_include_args_false_strips_args(self, tmp_path):
        """Verify include_args=False strips args_summary."""
        config = AuditConfig(include_args=False, log_to_project=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry(args_summary={"path": "/secret"})
        al.log(entry)

        jsonl = tmp_path / "audit.jsonl"
        data = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert data["args_summary"] == {}

    def test_include_details_false_strips_details(self, tmp_path):
        """Verify include_details=False strips details."""
        config = AuditConfig(include_details=False, log_to_project=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry(details={"exit_code": 0})
        al.log(entry)

        jsonl = tmp_path / "audit.jsonl"
        data = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert data["details"] is None

    def test_multiple_entries_appended(self, tmp_path):
        """Verify multiple entries are appended to the same file."""
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        for i in range(3):
            entry = _make_entry(request_id=f"req-{i}")
            al.log(entry)

        jsonl = tmp_path / "audit.jsonl"
        lines = jsonl.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["request_id"] == f"req-{i}"

    def test_no_project_root_skips_project_write(self, tmp_path):
        """Verify project write is skipped when project_root is None."""
        config = AuditConfig()
        al = AuditLogger(global_log_dir=tmp_path, config=config)

        entry = _make_entry()
        al.log(entry, project_root=None)

        # Global should exist
        assert (tmp_path / "audit.jsonl").exists()
        # No project logs created in tmp_path root
        assert not (tmp_path / ".async-crud-mcp").exists()

    def test_global_dir_created_on_init(self, tmp_path):
        """Verify global log dir is created during __init__."""
        log_dir = tmp_path / "nested" / "logs"
        config = AuditConfig()
        AuditLogger(global_log_dir=log_dir, config=config)
        assert log_dir.exists()

    def test_global_dir_not_created_when_disabled(self, tmp_path):
        """Verify global log dir is NOT created when audit is disabled."""
        log_dir = tmp_path / "should_not_exist"
        config = AuditConfig(enabled=False)
        AuditLogger(global_log_dir=log_dir, config=config)
        assert not log_dir.exists()
