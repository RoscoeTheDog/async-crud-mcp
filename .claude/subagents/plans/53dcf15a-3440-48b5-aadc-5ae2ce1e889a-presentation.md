# Plan Update: Pre-Deployment Readiness Audit — Refinement Pass

## What Changed

- **Added**: R10 — Backport package-data declaration to daemon-service template (`PYPROJECT.template.md`)
- **Added**: R11 — Add wall-clock timeout to `async_search` loop to prevent unbounded rglob+read blocking
- **Added**: N2 analysis — Comprehensive timeout audit reveals critical gaps in `async_read`, `async_search`, `async_list`
- **Clarified**: R7 (C6 mkdir tool) now includes safety requirement: reject non-empty directories unless `force=True` flag explicitly passed (prevent `exist_ok=True` silent success)
- **Clarified**: R9 (C9 configure_claude_code.py) now confirms both CLI and Desktop config targets use identical `mcpServers` schema — no format difference; scope is simply `save_config()` function
- **Verified**: N1 (async_rename destination check) confirmed already implemented correctly at `async_rename.py:86` — no code change needed, downgraded to informational
- **Dropped**: Previous C7 (health.py uptime module-level stale time) — not retained in revised research; removed from this iteration

## Updated Files to Modify

| # | File | Change | Status |
|---|------|--------|--------|
| C1 | `src/async_crud_mcp/server.py` | Load/persist HMAC key from stable file | unchanged |
| C2 | `src/async_crud_mcp/tools/async_search.py` | Fix path boundary check with separator normalization | unchanged |
| C3 | `src/async_crud_mcp/core/lock_manager.py` | Add timeout parameter to `FileLock.acquire_read()` | unchanged |
| C4 | `src/async_crud_mcp/server.py` | Call `await logger.complete()` in shutdown | unchanged |
| C5 | `src/async_crud_mcp/models/responses.py` | Change SearchMatch context fields to `default=None` | unchanged |
| C6 | `src/async_crud_mcp/server.py` | Add new `async_mkdir_tool` with safety check for non-empty directories | **modified** |
| C7 | `src/async_crud_mcp/tools/async_search.py` | Add wall-clock timeout to file iteration loop | **new** |
| C8 | `pyproject.toml` | Declare daemon shell scripts as package data | unchanged |
| C9 | `scripts/configure_claude_code.py` | Use atomic write for `~/.claude.json` (applies to both CLI and Desktop) | unchanged |
| C10 | `src/async_crud_mcp/models/responses.py` | Add truncated flag and max_results to SearchResponse | unchanged |
| C11 | `src/async_crud_mcp/server.py` | Cancel and await config watcher task in shutdown | unchanged |
| C12 | `claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md` | Add `artifacts` stanza for shell scripts to `[tool.hatch.build.targets.wheel]` | **new** |

---

# Plan: Pre-Deployment Readiness Audit (Revised)

## Context

**Problem:** The async-crud-mcp MCP server is intended to replace native Claude Code tooling entirely. A comprehensive audit is needed to verify tool completeness, identify correctness bugs, token inefficiencies, and installation/infrastructure issues before production deployment. Recent user feedback identified five additional concerns: mkdir safety, rename destination validation, Desktop config format scope, global timeout gaps, and daemon-service template package-data backport.

**Solution:** Conduct pre-deployment analysis across architecture, logic, setup, debugging, and infrastructure. Fix critical issues (HMAC key persistence, path boundary in search, read lock starvation), apply timeout protections across all I/O operations, add missing tools with proper safety guards, and backport packaging fixes to downstream templates. Verify all findings with direct symbol references.

## Changes

### C1: `src/async_crud_mcp/server.py` (L313)
- **Currently:** `_recycle_hmac_key = os.urandom(32)` regenerated at module load
- **Change:** Load/persist HMAC key from stable file (`get_shared_dir() / "recycle_hmac.key"`) so recycle bin manifests remain valid across server restarts
- **Criticality:** Critical correctness bug — restore operations currently fail for files recycled before restart

### C2: `src/async_crud_mcp/tools/async_search.py` (L78)
- **Currently:** Uses bare `startswith()` check without separator normalization (e.g., `/project-foo` falsely matches `/project`)
- **Change:** Replace with separator-aware check: `startswith(str(project_root.resolve()) + os.sep)`
- **Criticality:** Critical security issue — path validation can be bypassed for files outside project root

### C3: `src/async_crud_mcp/core/lock_manager.py` (L64-93)
- **Currently:** `FileLock.acquire_read()` documents "no timeout, will wait indefinitely"
- **Change:** Add optional `timeout` parameter (default 60.0s) and wrap `entry.event.wait()` with `asyncio.wait_for(..., timeout=timeout)`, raising `LockTimeout` on expiry
- **Criticality:** High reliability — stuck write locks currently cause permanent read hangs in production

### C4: `src/async_crud_mcp/server.py` (L324-334)
- **Currently:** `_server_lifespan` finally block does not call `await logger.complete()`
- **Change:** Add `await logger.complete()` call before existing shutdown procedures to ensure final audit/debug logs are flushed
- **Criticality:** High reliability — final audit log entries may be lost on graceful shutdown

### C5: `src/async_crud_mcp/models/responses.py` (L502-503)
- **Currently:** `SearchMatch.context_before` and `context_after` use `default_factory=list`, serializing as empty lists even with `exclude_none=True`
- **Change:** Change to `default=None` so empty context suppresses serialization
- **Criticality:** Medium token efficiency — reduces search response size when context not requested

### C6: `src/async_crud_mcp/server.py` (new, ~L640 before async_list_tool)
- **Currently:** No standalone directory creation tool; agents must write dummy files to create directories
- **Change:** Add `async_mkdir_tool` that validates path via `path_validator.validate_operation(path, "write")`, then: (1) if target exists AND is non-empty AND `force=False`, return `ErrorResponse(FILE_EXISTS)`, (2) only call `os.makedirs(path, exist_ok=True)` when safe. Include `force: bool = False` parameter in request.
- **Criticality:** Medium missing tool — essential for clean workflows; safety guard prevents silent corruption of populated directories via `exist_ok=True`

### C7: `src/async_crud_mcp/tools/async_search.py` (L101-159)
- **Currently:** `rglob` + per-file `read_text` loop has no overall wall-clock timeout; unbounded iteration can block event loop for minutes
- **Change:** Record `start = time.monotonic()` before loop; after processing each file, check if `time.monotonic() - start > search_config.timeout_max`, break and set `truncated=True` if exceeded
- **Criticality:** Medium reliability (N2 timeout audit) — prevents pathological filesystem operations from blocking server

### C8: `pyproject.toml` (L44-45)
- **Currently:** `daemon/macos/launchd_installer.sh` and `daemon/linux/systemd_installer.sh` not declared as package data; wheel installs fail path resolution
- **Change:** Add `artifacts = ["src/async_crud_mcp/daemon/macos/*.sh", "src/async_crud_mcp/daemon/linux/*.sh"]` under `[tool.hatch.build.targets.wheel]`
- **Criticality:** Medium installation — fixes path resolution failure in `LaunchdInstaller` and `SystemdInstaller` for non-editable installs

### C9: `scripts/configure_claude_code.py` (L65-68)
- **Currently:** `config_path.write_text(...)` is non-atomic; interruption can corrupt `~/.claude.json` or `claude_desktop_config.json`
- **Change:** Write to temp file in same directory, then `Path.replace()` atomically. Applies to both CLI (`~/.claude.json`) and Desktop (`claude_desktop_config.json`) targets — function already handles both via path selection at `main():293-298`
- **Criticality:** Medium setup — prevents config file corruption for both targets

### C10: `src/async_crud_mcp/models/responses.py` (L510)
- **Currently:** `SearchResponse.total_matches` counts all matches regardless of `max_results` cutoff; agents cannot distinguish "exactly N" from "truncated at N"
- **Change:** Add `truncated: bool` and `max_results_applied: int` fields to allow agents to detect truncation without manual math
- **Criticality:** Low token efficiency — enables agent-side result handling optimization

### C11: `src/async_crud_mcp/server.py` (L324-334)
- **Currently:** `_config_watcher_task` is cancelled when project activated but not awaited during shutdown
- **Change:** Add explicit cancel and await in `_server_lifespan` finally block: `await _config_watcher_task` after catching `asyncio.CancelledError`
- **Criticality:** Low infrastructure — prevents logged errors after server shutdown begins

### C12: `claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md` (L10-43)
- **Currently:** Template ends after `[project.scripts]` and `[tool.hatch.build.targets.wheel]` sections without declaring package data for shell scripts
- **Change:** Add `artifacts = ["templates/daemon/macos/*.sh", "templates/daemon/linux/*.sh"]` stanza to `[tool.hatch.build.targets.wheel]` section in template (C8 backport)
- **Criticality:** Medium installation — backport ensures downstream projects inherit shell script packaging fix

## Files to Modify

| # | File | Change |
|---|------|--------|
| C1 | `src/async_crud_mcp/server.py` | Load/persist HMAC key from stable file for recycle bin |
| C2 | `src/async_crud_mcp/tools/async_search.py` | Fix path boundary check with separator normalization |
| C3 | `src/async_crud_mcp/core/lock_manager.py` | Add timeout parameter to `FileLock.acquire_read()` |
| C4 | `src/async_crud_mcp/server.py` | Call `await logger.complete()` in shutdown |
| C5 | `src/async_crud_mcp/models/responses.py` | Change SearchMatch context fields to `default=None` |
| C6 | `src/async_crud_mcp/server.py` | Add new `async_mkdir_tool` with non-empty directory safety check |
| C7 | `src/async_crud_mcp/tools/async_search.py` | Add wall-clock timeout to file iteration loop |
| C8 | `pyproject.toml` | Declare daemon shell scripts as package data |
| C9 | `scripts/configure_claude_code.py` | Use atomic write for config files (CLI and Desktop) |
| C10 | `src/async_crud_mcp/models/responses.py` | Add truncated flag and max_results to SearchResponse |
| C11 | `src/async_crud_mcp/server.py` | Cancel and await config watcher task in shutdown |
| C12 | `claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md` | Backport artifacts stanza for shell scripts |

## Verification

1. **C1 (HMAC key):** Confirm recycle bin manifests written after server restart with persisted key pass HMAC verification
2. **C2 (Path boundary):** Test that `/project-foo/file` in search from `/project` is correctly rejected (boundary check)
3. **C3 (Read lock timeout):** Verify read request times out (60s) if write lock held beyond timeout window
4. **C4 (Log drain):** Check that final audit log entries appear in logs after graceful shutdown
5. **C5 (Token bloat):** Compare SearchResponse size with `context_lines=0` before/after fix
6. **C6 (mkdir):** Call `async_mkdir_tool` on existing non-empty directory with `force=False` and verify `FILE_EXISTS` error; retry with `force=True` and verify success
7. **C7 (Search timeout):** Run search on large tree with `max_results` constraint, verify `truncated=True` when timeout exceeded
8. **C8 (Package data):** Install from wheel and verify shell scripts exist at expected paths
9. **C9 (Atomic write):** Simulate interrupt during config write; verify `.claude.json` not corrupted
10. **C10 (Truncation flag):** Verify search with `max_results=100` sets `truncated=True` when >100 matches exist
11. **C11 (Watcher cleanup):** Check no "task cancelled" errors logged after shutdown
12. **C12 (Template backport):** Generate project from daemon-service template, verify shell scripts packaged correctly in wheel

## Key Design Decisions

- **HMAC key file location:** Must survive server restarts and be machine-local; using `get_shared_dir()` ensures consistency across daemon/worker processes
- **Read lock timeout vs. deadlock detection:** Simple timeout is safer than deadlock graph; 60s default balances responsiveness with legitimate long-running reads
- **mkdir force flag:** Explicit opt-in prevents accidental data corruption; mirrors shell semantics of `-p` combined with safety check
- **Search timeout placement:** Wall-clock check in loop (C7) is simpler than async.timeout wrapper; integrates with existing `search_config.timeout_max`
- **Token efficiency vs. backwards compatibility:** All response schema changes use `default=None`, preserving existing tool contracts while optimizing serialization

## NOT Modified

- Tool count (now 25 tools with C6 mkdir addition) — no architectural changes beyond essential additions
- `async_copy_tool` — explicitly deprioritized; read+write pattern is acceptable with documentation
- `async_stat_tool` — deprioritized; `async_list` provides sufficient metadata
- `async_find_tool` (metadata search) — deprioritized; low priority for initial deployment
- TLS/mTLS — scoped out for production v1; local-only binding adequate
- Shell script path validation in `_get_script_path` — issue resolved at packaging level (C8, C12)
- `async_list` timeout — no lock acquisition; bounded in practice by filesystem; low priority

## Execution Order

1. **Phase 1 (Critical):** C1, C2, C3, C4 (correctness/reliability fixes first)
2. **Phase 2 (Medium):** C5, C6, C7, C8, C9 (token efficiency + missing tools + setup + timeouts)
3. **Phase 3 (Low):** C10, C11, C12 (refinements + template backport)

Each phase should be tested independently; later phases assume earlier phases are stable.
