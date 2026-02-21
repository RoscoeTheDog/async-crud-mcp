"""Structured audit logging for MCP tool calls.

Writes JSONL entries to global and per-project log files, and emits
structured loguru messages for real-time visibility.  Every tool call
is recorded with session context, timing, and outcome.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger


@dataclass
class AuditEntry:
    """A single audit record for one MCP tool call."""

    timestamp: str  # ISO 8601 UTC
    session_id: str
    client_id: str | None
    request_id: str
    project_root: str | None
    tool_name: str
    args_summary: dict = field(default_factory=dict)
    result_status: str = "unknown"
    result_code: str | None = None
    duration_ms: int = 0
    details: dict | None = None


@dataclass
class AuditConfig:
    """Plain dataclass mirroring the pydantic model for runtime use."""

    enabled: bool = True
    log_to_project: bool = True
    log_to_global: bool = True
    include_args: bool = True
    include_details: bool = True


class AuditLogger:
    """Fire-and-forget audit logger writing JSONL + loguru entries."""

    def __init__(self, global_log_dir: Path, config: AuditConfig) -> None:
        self._global_log_dir = global_log_dir
        self._config = config
        if config.enabled and config.log_to_global:
            self._global_log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry, project_root: Path | None = None) -> None:
        """Write an audit entry to loguru + JSONL files."""
        if not self._config.enabled:
            return

        # Respect config flags
        if not self._config.include_args:
            entry.args_summary = {}
        if not self._config.include_details:
            entry.details = None

        record = asdict(entry)
        line = json.dumps(record, default=str)

        # 1. Loguru (structured binding for downstream sinks)
        logger.bind(
            session_id=entry.session_id,
            tool=entry.tool_name,
            status=entry.result_status,
            duration_ms=entry.duration_ms,
        ).info(
            "audit: {tool} -> {status}",
            tool=entry.tool_name,
            status=entry.result_status,
        )

        # 2. Global JSONL (all projects, all sessions)
        if self._config.log_to_global:
            self._append(self._global_log_dir / "audit.jsonl", line)

        # 3. Per-project JSONL
        if self._config.log_to_project and project_root is not None:
            project_log_dir = project_root / ".async-crud-mcp" / "logs"
            project_log_dir.mkdir(parents=True, exist_ok=True)
            self._append(project_log_dir / "audit.jsonl", line)

    @staticmethod
    def _append(path: Path, line: str) -> None:
        """Append a single JSONL line.  Never raises."""
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass  # Audit must never break tool execution
