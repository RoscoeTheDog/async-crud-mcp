# Pre-Deployment Readiness Audit: async-crud-mcp (Revised)

## Context

Refined pre-deployment audit of async-crud-mcp, a production MCP server intended to replace
native Claude Code tooling (Read/Write/Edit/Glob/Grep/Bash) entirely. This revision addresses
five user feedback items: mkdir safety (C6), rename destination-existence validation (N1),
configure_claude_code.py Desktop format scope (C9), global timeout audit (N2), and package-data
backport to the daemon-service template (C8). All prior findings are preserved; new research
is integrated below.

---

## Findings

### 1. Architecture Completeness

The tool surface registers **24 MCP tools** across 4 categories. Coverage for native tools is
adequate: Read=async_read, Write=async_write, Edit=async_update, Glob=async_list, Grep=async_search,
Bash=async_exec.

**Gap: No `async_mkdir` tool.** Agents must write a dummy file to create a directory. A dedicated
`async_mkdir` is needed, but MUST guard against overwriting non-empty directories (exist_ok=True on
`os.makedirs` silently succeeds even when content is present). The correct behavior: if the target
exists AND is not empty, return an error unless a `force=True` flag is explicitly passed.

**Gap: No binary file support, no `async_copy_tool`.** Still present from prior pass (lower priority).

**N1 - async_rename_tool destination check already implemented.** `async_rename.py:86` confirms the
guard: `if not request.overwrite and os.path.exists(validated_new): return ErrorResponse(FILE_EXISTS)`.
No change needed. The `overwrite` parameter defaults to `False`, so the destination-existence check
is on by default. MCP docstring (`server.py`) should be verified to surface the `overwrite=False`
default to callers, but the logic is correct.

---

### 2. Redundancies and Token/Context Bloat

**`SearchMatch.context_before` / `context_after`** use `default_factory=list` (`responses.py:502-503`),
causing empty lists to serialize even with `exclude_none=True`. Change to `default=None` to suppress
when `context_lines=0`.

**`SearchResponse` missing `truncated` flag** (`responses.py:510`). Agents cannot distinguish
"exactly N matches" from "truncated at N". Add `truncated: bool` and `max_results_applied: int`.

---

### 3. Logic Issues

**HMAC key not persisted across restarts** (`server.py:313`). `_recycle_hmac_key = os.urandom(32)`
is regenerated each process start. All recycle bin manifests signed in a prior session fail
HMAC verification after restart. Files recycled before the current session cannot be restored.
Critical correctness bug.

**Path boundary check in `async_search` is separator-naive** (`async_search.py:78`). The check
`str(search_path.resolve()).startswith(str(project_root.resolve()))` can false-match `/project-foo`
against `/project` prefix without OS separator normalization. The fix in `path_validator.py:182`
(appending `os.sep`) is not applied here.

**Read lock starvation** (`lock_manager.py:64`). `acquire_read` documents "will wait indefinitely."
In production, a hung write lock causes all readers on that file to block forever with no
timeout or error.

**`logger.complete()` not called on shutdown** (`server.py:331`). The `_server_lifespan` finally
block omits `await logger.complete()` required by `logging_setup.py:65`. Final log entries are lost.

---

### 4. N2: Global Timeout Audit

Tools with write-lock acquisition all pass `request.timeout` to `lock_manager.acquire_write`,
which raises `LockTimeout` on expiry. These are **covered**: `async_write`, `async_update`,
`async_append`, `async_delete`, `async_rename`, `async_restore`, `async_batch_write`,
`async_batch_update`.

**Timeout gaps confirmed:**

- **`async_read` (`tools/async_read.py:61`)**: Calls `lock_manager.acquire_read(str(validated_path))`
  with no timeout parameter. `FileLock.acquire_read` (`lock_manager.py:64`) ignores the `timeout`
  argument and waits indefinitely. A hung write lock stalls all reads permanently. This is the
  most critical timeout gap.

- **`async_list` (`tools/async_list.py`)**: No lock acquisition, but directory listing over a
  deeply nested tree with millions of files (rglob) is unbounded. No timeout or item-count limit
  in the tool call itself.

- **`async_search` (`tools/async_search.py:101-104`)**: `rglob` + per-file `read_text` loop.
  No overall wall-clock timeout. A pathological glob on a large filesystem can block the event
  loop for minutes.

- **`async_status` (`tools/async_status.py`)**: No lock or timeout concern — purely in-memory.

- **`async_wait` (`tools/async_wait.py:89`)**: Correctly applies `wait_timeout` (clamped to 30s
  if `seconds <= 0`). Covered.

- **`async_exec` (`tools/async_exec.py:95`)**: Correctly clamps timeout to `shell_config.timeout_max`.
  Covered.

Summary of timeout gaps: **`async_read` (critical — indefinite lock wait)**, **`async_search`
(medium — unbounded rglob+read loop)**, **`async_list` (low — unbounded rglob)**.

---

### 5. C9: configure_claude_code.py — Desktop Format Research

`scripts/configure_claude_code.py` already handles both targets:
- **CLI path** (`get_claude_cli_config_path`, line 37): `~/.claude.json` — top-level `mcpServers` dict.
- **Desktop path** (`get_claude_desktop_config_path`, line 42): `~/AppData/Roaming/Claude/claude_desktop_config.json` (Windows), `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `~/.config/Claude/claude_desktop_config.json` (Linux).

**Both targets share the same schema:** top-level `mcpServers` dict with per-server entries.
The `add_mcp_server` and `remove_mcp_server` functions are format-agnostic — they operate on
`config["mcpServers"]` regardless of which file is passed. The `--desktop` flag selects the
path at `main():293-298` and dispatches to the same functions.

**Actual gap:** The `save_config` function (`configure_claude_code.py:65-68`) uses
`config_path.write_text(...)` — a non-atomic write. If interrupted, `~/.claude.json` or
`claude_desktop_config.json` can be left partially written (truncated JSON). This bug affects
**both** config files. The fix is a temp-file-then-rename pattern. The same non-atomic bug
exists in the daemon-service template at
`claude-code-tooling/claude-mcp/daemon-service/resources/snippets/scripts/configure_claude_code.py:65-68`.

**No format difference exists** between CLI and Desktop — the user's concern about "fundamentally
different formats" is not reflected in the actual code. Both files use identical `mcpServers`
structure (SSE transport entry). The scope of R9 is simply the `save_config` function, which
already handles both targets through path selection.

---

### 6. Setup and Installation Issues

**Shell scripts not declared as package data** (`pyproject.toml:44-45`). The hatchling config
only declares `packages = ["src/async_crud_mcp"]`. The macOS/Linux installer shell scripts
(`daemon/macos/launchd_installer.sh`, `daemon/linux/systemd_installer.sh`) are not declared
in `[tool.hatch.build.targets.wheel]`. `LaunchdInstaller._get_script_path` (`daemon/installer.py:230`)
and `SystemdInstaller._get_script_path` (`daemon/installer.py:352`) use `__file__`-relative
paths — these work for editable installs but fail in wheel installs.

**C8 Backport:** The daemon-service template at
`claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md` also lacks
a `package_data` / `include` section for shell scripts. The `PYPROJECT.template.md` template
ends after listing `[project.scripts]` and `[tool.hatch.build.targets.wheel]` entries without
declaring script data files. The backport adds an `include` stanza to the template's
`[tool.hatch.build.targets.wheel]` section.

**`setup_cmd.py` silently swallows `OSError`** (`cli/setup_cmd.py:120-141`). Service install
failure is caught but wizard continues, leaving config-but-no-daemon state.

**`configure_claude_code.py` non-atomic write** (described under C9 above).

---

### 7. Debugging Issues

**`_server_lifespan` has no "server ready" log** (`server.py:325`). No startup completion message
before first tool call.

**`_config_watcher_task` not awaited on shutdown** (`server.py:1125`). May log errors after teardown.

---

## Recommendations

**R1 (Critical — Correctness):** Persist HMAC key to stable file in `server.py:313`. Change
`_recycle_hmac_key = os.urandom(32)` to load-or-generate from `get_shared_dir() / "recycle_hmac.key"`.
Symbol: module-level `_recycle_hmac_key` initialization at `server.py:313`.

**R2 (Critical — Security):** Fix path boundary in `async_search.py:78`. Replace bare
`startswith(str(project_root.resolve()))` with `startswith(str(project_root.resolve()) + os.sep)`
to prevent `/project-foo` matching `/project`. Symbol: `async_search` at `async_search.py:78`.

**R3 (High — Reliability / N2):** Add timeout to `FileLock.acquire_read` at `lock_manager.py:64`.
Change signature to `async def acquire_read(self, request_id: str, timeout: float = 60.0)` and
wrap `entry.event.wait()` in `asyncio.wait_for(entry.event.wait(), timeout=timeout)`, raising
`LockTimeout` on expiry. Symbol: `FileLock.acquire_read` at `lock_manager.py:64`.

**R4 (High — Reliability / N2):** Propagate read timeout through `async_read`. Pass
`request.timeout` (or a sensible default) to `lock_manager.acquire_read` at `tools/async_read.py:61`.
Symbol: `async_read` at `tools/async_read.py:61`. Derives from N2 timeout audit.

**R5 (High — Logging):** Add `await logger.complete()` to `_server_lifespan` finally block at
`server.py:331`. Symbol: `_server_lifespan` at `server.py:324`.

**R6 (Medium — Token Efficiency):** Change `SearchMatch.context_before` and `context_after`
from `default_factory=list` to `default=None` at `responses.py:502-503`. Symbol:
`SearchMatch.context_before` and `SearchMatch.context_after` at `responses.py:502-503`.

**R7 (Medium — Missing Tool / C6):** Add `async_mkdir_tool` to `server.py` before `async_list_tool`.
Implementation must: (1) validate path via `path_validator.validate_operation(path, "write")`,
(2) if the target exists AND is non-empty AND `force=False`, return `ErrorResponse(FILE_EXISTS)`,
(3) only call `os.makedirs(path, exist_ok=True)` when safe. The `exist_ok=True` guard without the
non-empty check would silently succeed on populated directories — this is the safety gap the user
flagged. Symbol: new `@mcp.tool()` wrapper, insert at `server.py` before `async_list_tool`.

**R8 (Medium — Installation):** Declare shell scripts as package data in `pyproject.toml:44-45`.
Add `artifacts = ["src/async_crud_mcp/daemon/macos/*.sh", "src/async_crud_mcp/daemon/linux/*.sh"]`
under `[tool.hatch.build.targets.wheel]`. Symbol: `[tool.hatch.build.targets.wheel]` in
`pyproject.toml:44`.

**R9 (Medium — Setup):** Fix non-atomic write in `save_config` at `scripts/configure_claude_code.py:65-68`.
Replace `config_path.write_text(...)` with write-to-tempfile-then-`Path.replace()` (atomic rename)
in the same directory. This protects both `~/.claude.json` (CLI) and `claude_desktop_config.json`
(Desktop) since `save_config` handles both. Symbol: `save_config` at
`scripts/configure_claude_code.py:65`.

**R10 (Medium — Installation / C8):** Backport package-data declaration to daemon-service template.
Add `artifacts` stanza for `*.sh` files to `[tool.hatch.build.targets.wheel]` section in
`claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md`. Symbol:
`[tool.hatch.build.targets.wheel]` in `daemon-service/templates/PYPROJECT.template.md`.

**R11 (Medium — N2):** Add wall-clock timeout to `async_search` loop at `async_search.py:101`.
Wrap the per-file iteration in a deadline check: record `start = time.monotonic()` before the
loop; after processing each file, if `time.monotonic() - start > search_config.timeout_max`
(or a new `SearchConfig.timeout_seconds` field), break and set `truncated=True`. Symbol:
`async_search` file loop at `async_search.py:101-159`.

**R12 (Low — Token Efficiency):** Add `truncated: bool` and `max_results_applied: int` to
`SearchResponse` at `responses.py:510`. Symbol: `SearchResponse` at `responses.py:510`.

**R13 (Low — Infrastructure):** Cancel and await `_config_watcher_task` in `_server_lifespan`
finally block at `server.py:331`. Symbol: `_server_lifespan` at `server.py:324`.

---

## Files Identified

| File | Lines | Relevance |
|------|-------|-----------|
| `src/async_crud_mcp/server.py` | L313, L324-334, L373-922 | HMAC key (R1), lifespan (R5, R13), mkdir tool (R7) |
| `src/async_crud_mcp/tools/async_search.py` | L78, L101-159 | Path boundary (R2), loop timeout (R11) |
| `src/async_crud_mcp/core/lock_manager.py` | L64-93 | Read lock timeout (R3) |
| `src/async_crud_mcp/tools/async_read.py` | L61 | Read timeout propagation (R4) |
| `src/async_crud_mcp/models/responses.py` | L502-503, L510 | SearchMatch empty lists (R6), truncated flag (R12) |
| `scripts/configure_claude_code.py` | L65-68 | Non-atomic write, both CLI+Desktop targets (R9) |
| `pyproject.toml` | L44-45 | Shell script package data (R8) |
| `src/async_crud_mcp/tools/async_rename.py` | L86-91 | N1 validated: overwrite guard confirmed correct |
| `src/async_crud_mcp/daemon/installer.py` | L230-234, L352-356 | Script path resolution (context for R8) |
| `claude-code-tooling/claude-mcp/daemon-service/templates/PYPROJECT.template.md` | L10-43 | C8 backport: add artifacts stanza (R10) |

---

## Verification Results

- Files checked: 10 / Files in scope: 10
- Symbols verified:
  - `FileLock.acquire_read` confirmed at `lock_manager.py:64` — no timeout parameter
  - `async_read` lock call confirmed at `tools/async_read.py:61` — no timeout passed
  - `async_rename.py:86` — destination-existence check confirmed present and correct (`overwrite=False` default)
  - `save_config` at `scripts/configure_claude_code.py:65` — non-atomic `write_text` confirmed
  - `get_claude_desktop_config_path` at `scripts/configure_claude_code.py:42` — Desktop path already implemented
  - `SearchMatch` fields at `responses.py:502-503` — `default_factory=list` confirmed
  - `_recycle_hmac_key` at `server.py:313` — `os.urandom(32)` confirmed, not persisted
  - `async_search` path check at `async_search.py:78` — bare `startswith` confirmed
  - `[tool.hatch.build.targets.wheel]` at `pyproject.toml:44` — no `artifacts` stanza confirmed
  - Daemon-service template `PYPROJECT.template.md` — no package_data for shell scripts confirmed
- Corrections made:
  - N1 (async_rename destination check): Confirmed already implemented — no code change needed. Downgraded to informational finding only.
  - C9 (Desktop format scope): Confirmed Desktop path and format are already handled by existing functions. No separate function needed. R9 scope is simply `save_config` (applies to both targets).
  - `async_list` timeout: Confirmed no lock acquisition; bounded in practice by filesystem. Downgraded to low priority (not added as separate recommendation to avoid over-engineering).
  - `async_search` timeout confirmed as medium gap (R11 added).
