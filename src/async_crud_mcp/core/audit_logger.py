"""Structured audit logging for MCP tool calls.

Uses loguru sinks for 3-tier JSONL output (project, user, system).
Each tier gets rotation, retention, compression, and async-safety
via ``serialize=True`` and ``enqueue=True``.

Every tool call is recorded with session context, timing, and outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


def _audit_filter(record):
    """Loguru filter: only capture messages with audit=True in extra."""
    return record["extra"].get("audit", False)


class AuditLogger:
    """Audit logger using loguru sinks for 3-tier JSONL output."""

    def __init__(
        self,
        config: AuditConfig,
        user_log_dir: Path | None = None,
        system_log_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._project_sink_id: int | None = None
        self._current_project_root: Path | None = None
        self._sink_ids: list[int] = []

        if not config.enabled:
            return

        # Tier 2: User-level sink (LOCALAPPDATA/async-crud-mcp/logs/)
        if config.log_to_global and user_log_dir is not None:
            user_log_dir.mkdir(parents=True, exist_ok=True)
            sid = logger.add(
                str(user_log_dir / "audit.log"),
                filter=_audit_filter,
                serialize=True,
                rotation="10 MB",
                retention="30 days",
                compression="gz",
                enqueue=True,
                level="INFO",
            )
            self._sink_ids.append(sid)

        # Tier 3: System-level sink (ProgramData/async-crud-mcp/logs/)
        if config.log_to_global and system_log_dir is not None:
            try:
                system_log_dir.mkdir(parents=True, exist_ok=True)
                sid = logger.add(
                    str(system_log_dir / "audit.log"),
                    filter=_audit_filter,
                    serialize=True,
                    rotation="10 MB",
                    retention="90 days",
                    compression="gz",
                    enqueue=True,
                    level="INFO",
                )
                self._sink_ids.append(sid)
            except PermissionError:
                pass  # Non-admin users may not have ProgramData write access

    def set_project(self, project_root: Path | None) -> None:
        """Add/replace the project-level loguru sink when project activates."""
        if not self._config.enabled or not self._config.log_to_project:
            return

        # Remove old project sink
        if self._project_sink_id is not None:
            try:
                logger.remove(self._project_sink_id)
            except ValueError:
                pass
            self._project_sink_id = None
            self._current_project_root = None

        if project_root is None:
            return

        project_log_dir = project_root / ".async-crud-mcp" / "logs"
        project_log_dir.mkdir(parents=True, exist_ok=True)
        self._project_sink_id = logger.add(
            str(project_log_dir / "audit.log"),
            filter=_audit_filter,
            serialize=True,
            rotation="5 MB",
            retention="14 days",
            compression="gz",
            enqueue=True,
            level="INFO",
        )
        self._current_project_root = project_root

    def log(self, entry: AuditEntry) -> None:
        """Emit an audit entry via loguru with all fields bound."""
        if not self._config.enabled:
            return

        # Respect config flags
        args = entry.args_summary if self._config.include_args else {}
        details = entry.details if self._config.include_details else None

        logger.bind(
            audit=True,
            session_id=entry.session_id,
            client_id=entry.client_id,
            request_id=entry.request_id,
            project_root=entry.project_root,
            tool_name=entry.tool_name,
            args_summary=args,
            result_status=entry.result_status,
            result_code=entry.result_code,
            duration_ms=entry.duration_ms,
            details=details,
        ).info(
            "audit: {tool} -> {status} ({duration_ms}ms)",
            tool=entry.tool_name,
            status=entry.result_status,
            duration_ms=entry.duration_ms,
        )

    def close(self) -> None:
        """Remove all audit sinks (for shutdown/testing)."""
        for sid in self._sink_ids:
            try:
                logger.remove(sid)
            except ValueError:
                pass
        self._sink_ids.clear()
        if self._project_sink_id is not None:
            try:
                logger.remove(self._project_sink_id)
            except ValueError:
                pass
            self._project_sink_id = None
