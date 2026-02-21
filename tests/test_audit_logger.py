"""Unit tests for audit logger module (loguru-based 3-tier sinks)."""

import json
import time

from loguru import logger

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


def _flush_loguru():
    """Wait for loguru enqueued messages to be written."""
    # loguru enqueue=True uses a background thread; give it time to flush
    time.sleep(0.15)


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
    """Test the AuditLogger class with loguru sinks."""

    def test_writes_user_level_log(self, tmp_path):
        """Verify entries are written to user-level audit.log."""
        user_dir = tmp_path / "user_logs"
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            entry = _make_entry()
            al.log(entry)
            _flush_loguru()

            log_file = user_dir / "audit.log"
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8").strip()
            data = json.loads(content)
            assert data["record"]["extra"]["tool_name"] == "async_read_tool"
            assert data["record"]["extra"]["session_id"] == "test-session-1"
            assert data["record"]["extra"]["duration_ms"] == 42
            assert data["record"]["extra"]["audit"] is True
        finally:
            al.close()

    def test_writes_system_level_log(self, tmp_path):
        """Verify entries are written to system-level audit.log."""
        system_dir = tmp_path / "system_logs"
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(config=config, system_log_dir=system_dir)
        try:
            entry = _make_entry()
            al.log(entry)
            _flush_loguru()

            log_file = system_dir / "audit.log"
            assert log_file.exists()
            data = json.loads(log_file.read_text(encoding="utf-8").strip())
            assert data["record"]["extra"]["tool_name"] == "async_read_tool"
        finally:
            al.close()

    def test_writes_project_level_log(self, tmp_path):
        """Verify entries are written to project-level audit.log via set_project."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        config = AuditConfig(log_to_global=False)
        al = AuditLogger(config=config)
        try:
            al.set_project(project_dir)
            entry = _make_entry(project_root=str(project_dir))
            al.log(entry)
            _flush_loguru()

            project_log = project_dir / ".async-crud-mcp" / "logs" / "audit.log"
            assert project_log.exists()
            data = json.loads(project_log.read_text(encoding="utf-8").strip())
            assert data["record"]["extra"]["tool_name"] == "async_read_tool"
        finally:
            al.close()

    def test_triple_write(self, tmp_path):
        """Verify entries written to all three tiers simultaneously."""
        user_dir = tmp_path / "user"
        system_dir = tmp_path / "system"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config = AuditConfig()
        al = AuditLogger(config=config, user_log_dir=user_dir, system_log_dir=system_dir)
        try:
            al.set_project(project_dir)
            entry = _make_entry(project_root=str(project_dir))
            al.log(entry)
            _flush_loguru()

            assert (user_dir / "audit.log").exists()
            assert (system_dir / "audit.log").exists()
            assert (project_dir / ".async-crud-mcp" / "logs" / "audit.log").exists()
        finally:
            al.close()

    def test_disabled_writes_nothing(self, tmp_path):
        """Verify disabled config writes nothing and adds no sinks."""
        user_dir = tmp_path / "user"
        config = AuditConfig(enabled=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            entry = _make_entry()
            al.log(entry)
            _flush_loguru()

            assert not user_dir.exists()
            assert len(al._sink_ids) == 0
        finally:
            al.close()

    def test_include_args_false_strips_args(self, tmp_path):
        """Verify include_args=False strips args_summary."""
        user_dir = tmp_path / "user"
        config = AuditConfig(include_args=False, log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            entry = _make_entry(args_summary={"path": "/secret"})
            al.log(entry)
            _flush_loguru()

            data = json.loads((user_dir / "audit.log").read_text(encoding="utf-8").strip())
            assert data["record"]["extra"]["args_summary"] == {}
        finally:
            al.close()

    def test_include_details_false_strips_details(self, tmp_path):
        """Verify include_details=False strips details."""
        user_dir = tmp_path / "user"
        config = AuditConfig(include_details=False, log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            entry = _make_entry(details={"exit_code": 0})
            al.log(entry)
            _flush_loguru()

            data = json.loads((user_dir / "audit.log").read_text(encoding="utf-8").strip())
            assert data["record"]["extra"]["details"] is None
        finally:
            al.close()

    def test_multiple_entries_appended(self, tmp_path):
        """Verify multiple entries are appended to the same file."""
        user_dir = tmp_path / "user"
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            for i in range(3):
                entry = _make_entry(request_id=f"req-{i}")
                al.log(entry)
            _flush_loguru()

            lines = (user_dir / "audit.log").read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 3
            for i, line in enumerate(lines):
                data = json.loads(line)
                assert data["record"]["extra"]["request_id"] == f"req-{i}"
        finally:
            al.close()

    def test_no_project_set_skips_project_write(self, tmp_path):
        """Verify project write is skipped when set_project not called."""
        user_dir = tmp_path / "user"
        config = AuditConfig()
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            entry = _make_entry()
            al.log(entry)
            _flush_loguru()

            # User log should exist
            assert (user_dir / "audit.log").exists()
            # No project logs
            assert al._project_sink_id is None
        finally:
            al.close()

    def test_set_project_none_removes_sink(self, tmp_path):
        """Verify set_project(None) removes the project sink."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config = AuditConfig(log_to_global=False)
        al = AuditLogger(config=config)
        try:
            al.set_project(project_dir)
            assert al._project_sink_id is not None

            al.set_project(None)
            assert al._project_sink_id is None
        finally:
            al.close()

    def test_user_log_dir_created_on_init(self, tmp_path):
        """Verify user log dir is created during __init__."""
        user_dir = tmp_path / "nested" / "logs"
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            assert user_dir.exists()
        finally:
            al.close()

    def test_dir_not_created_when_disabled(self, tmp_path):
        """Verify dirs are NOT created when audit is disabled."""
        user_dir = tmp_path / "should_not_exist"
        config = AuditConfig(enabled=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            assert not user_dir.exists()
        finally:
            al.close()

    def test_close_removes_all_sinks(self, tmp_path):
        """Verify close() removes all sinks."""
        user_dir = tmp_path / "user"
        system_dir = tmp_path / "system"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config = AuditConfig()
        al = AuditLogger(config=config, user_log_dir=user_dir, system_log_dir=system_dir)
        al.set_project(project_dir)

        assert len(al._sink_ids) == 2
        assert al._project_sink_id is not None

        al.close()

        assert len(al._sink_ids) == 0
        assert al._project_sink_id is None

    def test_audit_filter_only_captures_audit_messages(self, tmp_path):
        """Verify that non-audit loguru messages do NOT appear in audit.log."""
        user_dir = tmp_path / "user"
        config = AuditConfig(log_to_project=False)
        al = AuditLogger(config=config, user_log_dir=user_dir)
        try:
            # Emit a regular (non-audit) loguru message
            logger.info("this is not an audit message")
            _flush_loguru()

            log_file = user_dir / "audit.log"
            if log_file.exists():
                content = log_file.read_text(encoding="utf-8").strip()
                assert content == "", "Non-audit messages should not appear in audit.log"
        finally:
            al.close()
