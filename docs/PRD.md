# async-crud-mcp - Product Requirements Document

**Status**: DRAFT
**Version**: 0.1.0
**Created**: 2026-02-12
**Authors**: Human + Claude
**MCP Server**: async-crud-mcp
**Python**: 3.12+
**Transport**: SSE (Streamable HTTP)

---

## 1. Problem Statement

### 1.1 Current State

AI agent orchestration systems (e.g., Claude Code with subagents) cannot safely dispatch file operations to multiple concurrent agents. Today, when a parent orchestrator delegates tasks to subagents that involve file modifications:

1. **Sequential bottleneck**: The orchestrator must reconcile all file changes after each subagent completes, serializing what should be parallel work.
2. **Stale state**: Subagent B reads a file, subagent A modifies it, subagent B writes its changes -- silently overwriting A's work.
3. **Expensive recovery**: When conflicts are detected, agents must re-read entire files (high token cost) before retrying, even if the conflict is localized to a few lines.
4. **No coordination primitive**: MCP provides no standard mechanism for agents to coordinate file access. Each agent uses its native `Read()`/`Write()` tools with no awareness of other agents.

### 1.2 Desired State

A dedicated MCP server that provides file-locking async CRUD operations. Agents replace their native file tools with `async_read()`, `async_write()`, `async_update()`, and `async_delete()` calls routed through this server. The server:

- Maintains a per-file FIFO request queue with read/write lock semantics
- Allows concurrent reads with near-zero latency
- Serializes write operations with configurable timeouts
- Returns **differential details** on contention instead of bare errors, enabling agents to re-craft updates without re-reading entire files (saving significant token overhead)

### 1.3 Key Insight: Diff-Based Contention Resolution

The most critical innovation is the contention response for `async_update()`. When agent B's update is blocked because agent A modified the same file first:

```
Traditional approach:
  1. Agent B sends update -> ERROR: file changed
  2. Agent B re-reads entire file (token cost: full file)
  3. Agent B re-computes update
  4. Agent B sends new update

async-crud-mcp approach:
  1. Agent B sends update -> CONTENTION response with diff
  2. Agent B reads diff (token cost: changed lines only)
  3. Agent B adjusts update based on diff
  4. Agent B sends new update
```

This eliminates the re-read round-trip and reduces token overhead proportional to the size of the change, not the size of the file.

---

## 2. Architecture

### 2.1 Infrastructure: Daemon Service Pattern

This server is built on the **daemon-service template** located at:

```
C:\Users\Admin\Documents\GitHub\claude-code-tooling\claude-mcp\daemon-service\
```

The template provides:

| Component | Template Source | Purpose |
|-----------|---------------|---------|
| Project scaffold | `OVERVIEW.template.md` | Design principles, per-user isolation |
| Bootstrap lifecycle | `BOOTSTRAP.template.md` | Session-aware start/stop |
| Service management | `SERVICE.template.md` | Windows/macOS/Linux service registration |
| Configuration | `CONFIG.template.md` | pydantic-settings with JSON + env vars |
| Python standards | `PYTHON_STACK.template.md` | pydantic, loguru, typer, uv |
| Installation | `INSTALLER.template.md` | Platform installers |
| CLI commands | `CLI_COMMANDS.template.md` | Typer command groups |
| Testing | `INTEGRATION.template.md` | Claude Desktop integration |

**Placeholders** (ADR-009 convention):

| Placeholder | Value |
|-------------|-------|
| `[APP_NAME]` | `async-crud-mcp` |
| `[DEFAULT_PORT]` | `8720` |
| `[PACKAGE_NAME]` | `async_crud_mcp` |

**Snippets to copy** from `daemon-service/resources/snippets/`:

| Snippet | Target |
|---------|--------|
| `common/paths.py` | `src/async_crud_mcp/daemon/paths.py` |
| `common/bootstrap_daemon.py` | `src/async_crud_mcp/daemon/bootstrap_daemon.py` |
| `common/config_watcher.py` | `src/async_crud_mcp/daemon/config_watcher.py` |
| `common/graceful_shutdown.py` | `src/async_crud_mcp/daemon/graceful_shutdown.py` |
| `common/logging_setup.py` | `src/async_crud_mcp/daemon/logging_setup.py` |
| `common/session_detector.py` | `src/async_crud_mcp/daemon/session_detector.py` |
| `common/config_init.py` | `src/async_crud_mcp/daemon/config_init.py` |
| `common/installer.py` | `src/async_crud_mcp/daemon/installer.py` |
| `common/health.py` | `src/async_crud_mcp/daemon/health.py` |
| `common/cli_app.py` | `src/async_crud_mcp/cli/__init__.py` |
| `common/quick_install.py` | `src/async_crud_mcp/cli/install.py` |
| `windows/bootstrap_service.py` | `src/async_crud_mcp/daemon/windows/bootstrap_service.py` |
| `windows/dispatcher.py` | `src/async_crud_mcp/daemon/windows/dispatcher.py` |
| `windows/session_detector.py` | `src/async_crud_mcp/daemon/windows/session_detector.py` |
| `macos/launchd.plist` | `src/async_crud_mcp/daemon/macos/launchd.plist` |
| `macos/launchd_installer.sh` | `src/async_crud_mcp/daemon/macos/launchd_installer.sh` |
| `linux/systemd.service` | `src/async_crud_mcp/daemon/linux/systemd.service` |
| `linux/systemd_installer.sh` | `src/async_crud_mcp/daemon/linux/systemd_installer.sh` |
| `scripts/setup.bat` | `scripts/setup.bat` |
| `scripts/setup.sh` | `scripts/setup.sh` |
| `scripts/installer.py` | `scripts/installer.py` |
| `scripts/uninstaller.py` | `scripts/uninstaller.py` |
| `scripts/bootstrap_uv.py` | `scripts/bootstrap_uv.py` |
| `scripts/build_installer.py` | `scripts/build_installer.py` |
| `scripts/configure_claude_code.py` | `scripts/configure_claude_code.py` |
| `scripts/test_server.py` | `scripts/test_server.py` |
| `scripts/test_server.bat` | `scripts/test_server.bat` |
| `scripts/test_server.sh` | `scripts/test_server.sh` |

### 2.2 High-Level Architecture

```
+-------------------------------------------------------------------+
|                     AI Agent (Claude, etc.)                        |
|                                                                   |
|  Instead of:           Uses:                                      |
|    Read("file.py")       async_read(path="file.py")               |
|    Write("file.py")      async_write(path="file.py", content=...) |
|    Edit("file.py")       async_update(path="file.py", ...)        |
|    Glob("*.py")          async_list(path="/dir", pattern="*.py")  |
|                          async_delete(path="file.py")              |
|                          async_rename(old_path=..., new_path=...)  |
|                          async_append(path=..., content=...)       |
+-----------------------------+-------------------------------------+
                              | MCP (SSE / Streamable HTTP)
                              v
+-------------------------------------------------------------------+
|                    async-crud-mcp Server                           |
|                   (FastMCP, port 8720)                             |
|                                                                   |
|  +---------------------+    +----------------------+              |
|  |   CRUD Tools        |    |   Batch / Utility    |              |
|  | async_read()        |    | async_batch_read()   |              |
|  | async_write()       |    | async_batch_write()  |              |
|  | async_update()      |    | async_batch_update() |              |
|  | async_delete()      |    | async_list()         |              |
|  | async_rename()      |    | async_append()       |              |
|  |                     |    | async_status()       |              |
|  +--------+------------+    +----------+-----------+              |
|           |                            |                          |
|  +--------v----------------------------v----+                     |
|  |  Lock Manager       |  Per-file FIFO queue                    |
|  |  - Read locks       |  Content hash tracking                  |
|  |  - Write locks      |  TTL-based expiry                       |
|  |  - Queue + FIFO     |  Deadlock prevention                    |
|  +--------+------------+-------------------+                      |
|           |                                                       |
|  +--------v----------+    +-------------------+                   |
|  |  File I/O Layer   |    |  File Watcher     |                   |
|  |  - Read with hash |    |  - watchdog       |                   |
|  |  - Write + fsync  |    |  - Hash registry  |                   |
|  |  - Diff engine    |    |    auto-update    |                   |
|  |  - Path validator |    |  - External edit  |                   |
|  +-------------------+    |    detection      |                   |
|                           +-------------------+                   |
|  +-------------------+                                            |
|  | Persistence Layer |  Optional: file hashes + pending queue     |
|  | (optional)        |  TTL-based stale entry purge on restart    |
|  +-------------------+                                            |
+-------------------------------------------------------------------+
```

### 2.3 Project Structure

```
async-crud-mcp/
+-- pyproject.toml
+-- README.md
+-- LICENSE
+-- docs/
|   +-- PRD.md                          # This document
+-- scripts/
|   +-- setup.bat                       # Windows installer wrapper (thin, delegates to installer.py)
|   +-- setup.sh                        # Unix installer wrapper (thin, delegates to installer.py)
|   +-- installer.py                    # Stdlib-only Python installer (install/uninstall/menu)
|   +-- uninstaller.py                  # Stdlib-only Python uninstaller
|   +-- bootstrap_uv.py                # Cross-platform uv bootstrap utility
|   +-- build_installer.py             # Python Embedded Bundle builder
|   +-- configure_claude_code.py       # Claude Code CLI configuration
|   +-- test_server.py                 # Post-install server verification
|   +-- test_server.bat                # Windows test wrapper
|   +-- test_server.sh                 # Unix test wrapper
+-- src/
|   +-- async_crud_mcp/
|       +-- __init__.py                 # __version__, package metadata
|       +-- __main__.py                 # Entry point: python -m async_crud_mcp
|       +-- server.py                   # FastMCP server setup + tool registration
|       +-- config.py                   # pydantic-settings configuration
|       +-- cli/                        # Typer CLI package (from CLI_COMMANDS.template.md)
|       |   +-- __init__.py             # Main Typer app with subcommand groups
|       |   +-- bootstrap.py            # bootstrap install/uninstall/start/stop/status/list
|       |   +-- daemon.py               # daemon start/stop/restart/status/logs
|       |   +-- config_cmd.py           # config init/show/edit/validate
|       |   +-- install.py              # quick-install + uninstall commands
|       |   +-- setup.py                # Per-user setup wizard (no admin)
|       +-- tools/
|       |   +-- __init__.py
|       |   +-- async_read.py           # async_read() MCP tool
|       |   +-- async_write.py          # async_write() MCP tool
|       |   +-- async_update.py         # async_update() MCP tool
|       |   +-- async_delete.py         # async_delete() MCP tool
|       |   +-- async_rename.py         # async_rename() MCP tool
|       |   +-- async_append.py         # async_append() MCP tool
|       |   +-- async_list.py           # async_list() MCP tool
|       |   +-- async_status.py         # async_status() MCP tool
|       |   +-- async_batch.py          # async_batch_read/write/update() MCP tools
|       +-- core/
|       |   +-- __init__.py
|       |   +-- lock_manager.py         # File lock manager + FIFO queue
|       |   +-- file_io.py              # Atomic file operations + hashing
|       |   +-- diff_engine.py          # Diff computation (JSON + unified)
|       |   +-- path_validator.py       # Access control + base directory enforcement
|       |   +-- file_watcher.py         # OS filesystem watcher (watchdog)
|       |   +-- persistence.py          # Optional state persistence
|       +-- models/
|       |   +-- __init__.py
|       |   +-- requests.py             # Pydantic request models
|       |   +-- responses.py            # Pydantic response models
|       +-- daemon/                     # From daemon-service template snippets
|           +-- __init__.py
|           +-- paths.py               # Cross-platform path resolution (config, logs, data)
|           +-- bootstrap_daemon.py    # Session-aware bootstrap loop
|           +-- config_watcher.py      # Debounced config file watching
|           +-- graceful_shutdown.py   # Graceful MCP server shutdown
|           +-- logging_setup.py       # Loguru setup (enqueue=True, rotation)
|           +-- session_detector.py    # Cross-platform session detection
|           +-- config_init.py         # Config generation + find_available_port()
|           +-- installer.py           # ABC factory installer pattern
|           +-- health.py              # Application health check + port listening
|           +-- windows/
|           |   +-- __init__.py
|           |   +-- bootstrap_service.py  # pywin32 Windows Service (ADR-011)
|           |   +-- dispatcher.py         # Multi-User Dispatcher (ADR-008, ADR-012)
|           |   +-- session_detector.py   # WTS API session detection
|           +-- macos/
|           |   +-- launchd.plist         # LaunchAgent template
|           |   +-- launchd_installer.sh  # macOS service installer
|           +-- linux/
|               +-- systemd.service       # systemd user service unit
|               +-- systemd_installer.sh  # Linux service installer
+-- tests/
    +-- __init__.py
    +-- conftest.py
    +-- test_lock_manager.py
    +-- test_file_io.py
    +-- test_diff_engine.py
    +-- test_file_watcher.py
    +-- test_tools/
    |   +-- test_async_read.py
    |   +-- test_async_write.py
    |   +-- test_async_update.py
    |   +-- test_async_delete.py
    |   +-- test_async_rename.py
    |   +-- test_async_append.py
    |   +-- test_async_list.py
    |   +-- test_async_batch.py
    +-- test_integration/
        +-- test_concurrent_agents.py
        +-- test_contention.py
        +-- test_external_modification.py
        +-- test_persistence.py
```

---

## 3. MCP Tool Specifications

### 3.1 async_read()

**Purpose**: Read file content with consistent response schema and optional line indexing.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path to the file |
| `offset` | `int` | No | `0` | Starting line number (0-based) |
| `limit` | `int` | No | `null` | Maximum number of lines to return. `null` = all lines |
| `encoding` | `string` | No | `"utf-8"` | File encoding |

**Behavior**:
1. Validate `path` against configured base directories (reject if outside)
2. Acquire shared read lock (non-blocking; multiple concurrent reads allowed)
3. Read file content, applying `offset`/`limit` if specified
4. Compute content hash (SHA-256 of full file content, regardless of offset/limit)
5. Release read lock
6. Return response

**Response** (success):

```json
{
  "status": "ok",
  "path": "/abs/path/to/file.py",
  "content": "file content here...",
  "encoding": "utf-8",
  "hash": "sha256:a1b2c3d4...",
  "total_lines": 150,
  "offset": 0,
  "limit": null,
  "lines_returned": 150,
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Response** (error):

```json
{
  "status": "error",
  "error_code": "FILE_NOT_FOUND",
  "message": "File does not exist: /abs/path/to/file.py",
  "path": "/abs/path/to/file.py"
}
```

**Error codes**: `FILE_NOT_FOUND`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `ENCODING_ERROR`

**Performance**: Near-instantaneous. Read locks do not block other reads. Reads only block behind an active write lock on the same file.

---

### 3.2 async_write()

**Purpose**: Create a new file. Fails if the file already exists (use `async_update()` for existing files).

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path for the new file |
| `content` | `string` | Yes | - | File content to write |
| `encoding` | `string` | No | `"utf-8"` | File encoding |
| `create_dirs` | `bool` | No | `true` | Create parent directories if they don't exist |
| `timeout` | `float` | No | `30.0` | Seconds to wait for lock acquisition |

**Behavior**:
1. Validate `path` against configured base directories
2. Check that file does NOT exist (return `FILE_EXISTS` error if it does)
3. Acquire exclusive write lock with timeout (queue behind existing locks, FIFO)
4. Create parent directories if `create_dirs=true`
5. Write content atomically (write to temp file, then rename)
6. Compute and store content hash
7. Release write lock
8. Return response

**Response** (success):

```json
{
  "status": "ok",
  "path": "/abs/path/to/new_file.py",
  "hash": "sha256:a1b2c3d4...",
  "bytes_written": 1024,
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Error codes**: `FILE_EXISTS`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `LOCK_TIMEOUT`, `WRITE_ERROR`

---

### 3.3 async_update()

**Purpose**: Update an existing file with diff-based contention resolution.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path to the file |
| `expected_hash` | `string` | Yes | - | Hash from the agent's last `async_read()` of this file |
| `content` | `string` | Conditional | - | Full replacement content (mutually exclusive with `patches`) |
| `patches` | `list[Patch]` | Conditional | - | List of edit operations (mutually exclusive with `content`) |
| `encoding` | `string` | No | `"utf-8"` | File encoding |
| `timeout` | `float` | No | `30.0` | Seconds to wait for lock acquisition |
| `diff_format` | `string` | No | `"json"` | Format for contention diff: `"json"` or `"unified"` |

**Patch object** (when using `patches` mode):

```json
{
  "old_string": "text to find",
  "new_string": "replacement text"
}
```

**Behavior**:
1. Validate `path` against configured base directories
2. Check that file exists (return `FILE_NOT_FOUND` if not)
3. Acquire exclusive write lock with timeout (FIFO queue behind existing locks)
4. **Hash comparison**: Read current file, compute hash, compare to `expected_hash`
   - **Match**: Apply update (full content replacement or patches), compute new hash, release lock, return success
   - **Mismatch**: File was modified by another agent since this agent's last read. Compute diff between the version the agent expected and the current version. Return **contention response** with diff details. Do NOT apply the update. Release lock.
5. Return response

**Response** (success -- hash matched, update applied):

```json
{
  "status": "ok",
  "path": "/abs/path/to/file.py",
  "previous_hash": "sha256:old...",
  "hash": "sha256:new...",
  "bytes_written": 2048,
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Response** (contention -- hash mismatch, update NOT applied):

```json
{
  "status": "contention",
  "path": "/abs/path/to/file.py",
  "expected_hash": "sha256:what_agent_expected...",
  "current_hash": "sha256:what_file_actually_is...",
  "message": "File was modified by another operation. Diff provided for update adjustment.",
  "diff": {
    "format": "json",
    "changes": [
      {
        "type": "modified",
        "start_line": 10,
        "end_line": 12,
        "old_content": "    old line 1\n    old line 2\n    old line 3",
        "new_content": "    new line 1\n    new line 2",
        "context_before": "# surrounding code above",
        "context_after": "# surrounding code below"
      },
      {
        "type": "added",
        "start_line": 25,
        "new_content": "    brand_new_line()",
        "context_before": "    existing_line()",
        "context_after": "    another_existing_line()"
      },
      {
        "type": "removed",
        "start_line": 40,
        "end_line": 42,
        "old_content": "    removed_line_1()\n    removed_line_2()\n    removed_line_3()",
        "context_before": "    keep_this()",
        "context_after": "    keep_this_too()"
      }
    ],
    "summary": {
      "lines_added": 1,
      "lines_removed": 3,
      "lines_modified": 3,
      "regions_changed": 3
    }
  },
  "patches_applicable": false,
  "conflicts": [
    {"patch_index": 0, "reason": "old_string not found in current version"},
    {"patch_index": 2, "reason": "old_string found but surrounding context changed"}
  ],
  "non_conflicting_patches": [1],
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Patch applicability fields** (present only when request used `patches` mode):

| Field | Type | Description |
|-------|------|-------------|
| `patches_applicable` | `bool` | `true` if ALL patches can still be applied to the current file version |
| `conflicts` | `list` | List of patches that cannot be applied, with `patch_index` and `reason` |
| `non_conflicting_patches` | `list[int]` | Indices of patches that CAN still be applied to the current version |

When `patches_applicable=true`, the agent can re-submit the same patches with the `current_hash` -- the server will apply them successfully. When `false`, the agent must adjust conflicting patches based on the diff.

**Response** (contention -- unified diff format):

```json
{
  "status": "contention",
  "path": "/abs/path/to/file.py",
  "expected_hash": "sha256:what_agent_expected...",
  "current_hash": "sha256:what_file_actually_is...",
  "message": "File was modified by another operation. Diff provided for update adjustment.",
  "diff": {
    "format": "unified",
    "content": "--- expected\n+++ current\n@@ -10,3 +10,2 @@\n-    old line 1\n-    old line 2\n-    old line 3\n+    new line 1\n+    new line 2\n",
    "summary": {
      "lines_added": 1,
      "lines_removed": 3,
      "lines_modified": 3,
      "regions_changed": 3
    }
  },
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Error codes**: `FILE_NOT_FOUND`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `LOCK_TIMEOUT`, `INVALID_PATCH`, `CONTENT_OR_PATCHES_REQUIRED`

**Agent workflow on contention**:
1. Receive contention response with diff
2. Examine diff to understand what changed
3. Adjust the intended update based on the diff
4. Re-read the `current_hash` from the contention response
5. Send a new `async_update()` with `expected_hash` set to `current_hash`

---

### 3.4 async_delete()

**Purpose**: Delete a file with lock coordination and optional contention detection.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path to the file |
| `expected_hash` | `string` | No | `null` | If provided, delete only if file hash matches (contention check) |
| `timeout` | `float` | No | `30.0` | Seconds to wait for lock acquisition |
| `diff_format` | `string` | No | `"json"` | Format for contention diff: `"json"` or `"unified"` |

**Behavior**:
1. Validate `path` against configured base directories
2. Check that file exists (return `FILE_NOT_FOUND` if not)
3. Acquire exclusive write lock with timeout (FIFO)
4. If `expected_hash` is provided:
   - Compute current file hash
   - If mismatch: return contention response with diff (same format as `async_update()`)
   - If match: proceed with deletion
5. If `expected_hash` is not provided: proceed with deletion unconditionally
6. Delete file
7. Remove file from hash tracking
8. Release lock
9. Return response

**Response** (success):

```json
{
  "status": "ok",
  "path": "/abs/path/to/file.py",
  "deleted_hash": "sha256:last_known...",
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Response** (contention): Same format as `async_update()` contention response.

**Error codes**: `FILE_NOT_FOUND`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `LOCK_TIMEOUT`, `DELETE_ERROR`

---

### 3.5 async_status()

**Purpose**: Query server state, lock status, and queue depth for monitored files.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | No | `null` | If provided, return status for this specific file. If `null`, return global status. |

**Response** (global):

```json
{
  "status": "ok",
  "server": {
    "version": "0.1.0",
    "uptime_seconds": 3600,
    "transport": "sse",
    "port": 8720,
    "persistence": "enabled"
  },
  "tracked_files": 12,
  "active_locks": {
    "read": 3,
    "write": 1
  },
  "queue_depth": 2,
  "base_directories": ["/home/user/project", "/tmp/workspace"]
}
```

**Response** (per-file):

```json
{
  "status": "ok",
  "path": "/abs/path/to/file.py",
  "exists": true,
  "hash": "sha256:current...",
  "lock_state": "write_locked",
  "queue_depth": 1,
  "active_readers": 0,
  "pending_requests": [
    {
      "type": "update",
      "queued_at": "2026-02-12T17:30:00Z",
      "timeout_at": "2026-02-12T17:30:30Z"
    }
  ]
}
```

---

### 3.6 async_batch_read()

**Purpose**: Read multiple files in a single MCP call. Reduces round-trip overhead.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `files` | `list[BatchReadItem]` | Yes | - | List of files to read |

**BatchReadItem**:

```json
{
  "path": "/abs/path/to/file.py",
  "offset": 0,
  "limit": null,
  "encoding": "utf-8"
}
```

**Response**:

```json
{
  "status": "ok",
  "results": [
    {
      "status": "ok",
      "path": "/abs/path/to/file.py",
      "content": "...",
      "hash": "sha256:...",
      "total_lines": 100,
      "offset": 0,
      "limit": null,
      "lines_returned": 100,
      "timestamp": "2026-02-12T17:30:00Z"
    },
    {
      "status": "error",
      "path": "/abs/path/to/missing.py",
      "error_code": "FILE_NOT_FOUND",
      "message": "File does not exist"
    }
  ],
  "summary": {
    "total": 2,
    "succeeded": 1,
    "failed": 1
  }
}
```

---

### 3.7 async_batch_write()

**Purpose**: Create multiple new files in a single MCP call.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `files` | `list[BatchWriteItem]` | Yes | - | List of files to create |
| `timeout` | `float` | No | `30.0` | Per-file timeout for lock acquisition |

**BatchWriteItem**:

```json
{
  "path": "/abs/path/to/file.py",
  "content": "file content...",
  "encoding": "utf-8",
  "create_dirs": true
}
```

**Response**: Same structure as `async_batch_read()` with per-file success/error results.

**Atomicity**: Batch writes are NOT transactional. Each file is written independently. If file 2 of 5 fails, files 1, 3, 4, 5 may still succeed. The response reports per-file status.

---

### 3.8 async_list()

**Purpose**: List directory contents with optional glob filtering. Provides coordinated directory awareness so agents don't need to fall back to native `Glob()`/`Read()` tools that bypass the server.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path to the directory |
| `pattern` | `string` | No | `"*"` | Glob pattern to filter results (e.g., `"*.py"`, `"test_*"`) |
| `recursive` | `bool` | No | `false` | If true, recurse into subdirectories |
| `include_hashes` | `bool` | No | `false` | If true, include content hashes for files the server has tracked |

**Behavior**:
1. Validate `path` against configured base directories
2. Check that directory exists (return `DIR_NOT_FOUND` if not)
3. List directory contents, applying `pattern` filter
4. If `include_hashes=true`, attach cached hashes from the hash registry for any files the server has previously read/written (hash is `null` for untracked files)
5. Return response

**Response** (success):

```json
{
  "status": "ok",
  "path": "/abs/path/to/dir",
  "entries": [
    {
      "name": "file.py",
      "type": "file",
      "size_bytes": 1024,
      "modified": "2026-02-12T17:30:00Z",
      "hash": "sha256:a1b2c3d4..."
    },
    {
      "name": "subdir",
      "type": "directory",
      "modified": "2026-02-12T17:00:00Z"
    }
  ],
  "total_entries": 2,
  "pattern": "*",
  "recursive": false,
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Error codes**: `DIR_NOT_FOUND`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`

**Note**: This tool does NOT acquire locks. It provides a snapshot of directory state. Files may be created or deleted between the listing and subsequent operations.

**Known limitation**: Batch reads are NOT a consistent snapshot. Each file is read independently with its own read lock. By the time the response reaches the agent, earlier file hashes may be stale if another agent modified those files during the batch. Agents should treat batch read hashes as "best effort" starting points and expect contention on subsequent updates.

---

### 3.9 async_rename()

**Purpose**: Atomically rename or move a file with lock coordination on both source and destination paths.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `old_path` | `string` | Yes | - | Absolute path to the existing file |
| `new_path` | `string` | Yes | - | Absolute path for the new location |
| `expected_hash` | `string` | No | `null` | If provided, rename only if source file hash matches |
| `overwrite` | `bool` | No | `false` | If true, overwrite destination if it exists |
| `create_dirs` | `bool` | No | `true` | Create parent directories for `new_path` if they don't exist |
| `timeout` | `float` | No | `30.0` | Seconds to wait for lock acquisition |
| `diff_format` | `string` | No | `"json"` | Format for contention diff if `expected_hash` mismatches |

**Behavior**:
1. Validate both `old_path` and `new_path` against configured base directories
2. Check that `old_path` exists (return `FILE_NOT_FOUND` if not)
3. If `overwrite=false`, check that `new_path` does NOT exist (return `FILE_EXISTS` if it does)
4. Acquire exclusive write locks on BOTH paths with timeout. Lock ordering: alphabetical by path to prevent deadlocks between concurrent renames.
5. If `expected_hash` provided: compute current hash of `old_path`. On mismatch, return contention response (same format as `async_update()`). Release locks.
6. Create parent directories for `new_path` if `create_dirs=true`
7. Rename file (OS-level rename, atomic on same filesystem)
8. Update hash registry: remove `old_path`, add `new_path`
9. Release both locks
10. Return response

**Response** (success):

```json
{
  "status": "ok",
  "old_path": "/abs/path/to/old.py",
  "new_path": "/abs/path/to/new.py",
  "hash": "sha256:a1b2c3d4...",
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Error codes**: `FILE_NOT_FOUND`, `FILE_EXISTS`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `LOCK_TIMEOUT`, `RENAME_ERROR`

**Cross-filesystem note**: If `old_path` and `new_path` are on different filesystems, the rename falls back to copy + delete (not atomic). The response includes `"cross_filesystem": true` in this case.

---

### 3.10 async_batch_update()

**Purpose**: Update multiple existing files in a single MCP call with per-file contention resolution.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `files` | `list[BatchUpdateItem]` | Yes | - | List of files to update |
| `timeout` | `float` | No | `30.0` | Per-file timeout for lock acquisition |
| `diff_format` | `string` | No | `"json"` | Format for contention diffs |

**BatchUpdateItem**:

```json
{
  "path": "/abs/path/to/file.py",
  "expected_hash": "sha256:...",
  "content": "full replacement content",
  "patches": [{"old_string": "...", "new_string": "..."}],
  "encoding": "utf-8"
}
```

Note: `content` and `patches` are mutually exclusive per file, same as `async_update()`.

**Response**:

```json
{
  "status": "ok",
  "results": [
    {
      "status": "ok",
      "path": "/abs/path/to/file1.py",
      "previous_hash": "sha256:old...",
      "hash": "sha256:new...",
      "bytes_written": 2048,
      "timestamp": "2026-02-12T17:30:00Z"
    },
    {
      "status": "contention",
      "path": "/abs/path/to/file2.py",
      "expected_hash": "sha256:expected...",
      "current_hash": "sha256:actual...",
      "message": "File was modified by another operation.",
      "diff": { "format": "json", "changes": [], "summary": {} },
      "patches_applicable": false,
      "conflicts": [{"patch_index": 0, "reason": "old_string not found in current version"}]
    }
  ],
  "summary": {
    "total": 2,
    "succeeded": 1,
    "contention": 1,
    "failed": 0
  }
}
```

**Atomicity**: NOT transactional. Each file is updated independently. If file 2 has contention, file 1 may have already been written. The response reports per-file status so the agent can retry only the failed files.

---

### 3.11 async_append()

**Purpose**: Append content to a file without reading the full file first. Efficient for log files, data collection, and incremental output.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | - | Absolute path to the file |
| `content` | `string` | Yes | - | Content to append |
| `encoding` | `string` | No | `"utf-8"` | File encoding |
| `create_if_missing` | `bool` | No | `false` | Create the file if it does not exist |
| `create_dirs` | `bool` | No | `true` | Create parent directories if `create_if_missing=true` |
| `separator` | `string` | No | `""` | String to insert before the appended content (e.g., `"\n"`) |
| `timeout` | `float` | No | `30.0` | Seconds to wait for lock acquisition |

**Behavior**:
1. Validate `path` against configured base directories
2. If file does not exist and `create_if_missing=false`, return `FILE_NOT_FOUND`
3. If file does not exist and `create_if_missing=true`, create file (with parent dirs if needed)
4. Acquire exclusive write lock with timeout (FIFO)
5. Append `separator` + `content` to end of file
6. Compute and update content hash for the full file
7. Release write lock
8. Return response

**Response** (success):

```json
{
  "status": "ok",
  "path": "/abs/path/to/file.log",
  "hash": "sha256:new...",
  "bytes_appended": 256,
  "total_size_bytes": 4096,
  "timestamp": "2026-02-12T17:30:00Z"
}
```

**Error codes**: `FILE_NOT_FOUND`, `ACCESS_DENIED`, `PATH_OUTSIDE_BASE`, `LOCK_TIMEOUT`, `WRITE_ERROR`, `FILE_TOO_LARGE`

**Note**: No `expected_hash` parameter. Appends are inherently additive -- they don't conflict with other appends. If the agent needs contention detection on appends, use `async_update()` instead.

---

## 4. Core Components

### 4.1 Lock Manager (`core/lock_manager.py`)

The lock manager provides per-file read/write locking with FIFO queue semantics.

**Lock Semantics**:

| Operation | Lock Type | Concurrent Reads | Concurrent Writes |
|-----------|-----------|-------------------|-------------------|
| `async_read` | Shared (read) | Yes | Blocked by active write |
| `async_write` | Exclusive (write) | Blocks new reads | No |
| `async_update` | Exclusive (write) | Blocks new reads | No |
| `async_delete` | Exclusive (write) | Blocks new reads | No |
| `async_rename` | Exclusive (write) x2 | Blocks on both paths | No (alphabetical lock order) |
| `async_append` | Exclusive (write) | Blocks new reads | No |
| `async_list` | None | N/A | N/A |

**FIFO Queue**:
- Each file path has an independent queue
- Requests are processed in arrival order (FIFO)
- Write requests queue behind existing read AND write locks
- Read requests queue behind existing write locks only
- Multiple pending reads can be promoted simultaneously when a write lock releases

**Timeout Handling**:
- Each write request specifies a timeout (default: 30s)
- If the lock is not acquired within the timeout, the request returns `LOCK_TIMEOUT`
- Timed-out requests are removed from the queue
- Read requests have no timeout (they proceed immediately unless a write lock is active)

**TTL-Based Expiry** (for persistence mode):
- Each lock entry has a TTL derived from its timeout parameter
- On server restart, the persistence layer loads saved state and purges entries whose TTL has expired
- This prevents deadlocks from orphaned locks when the server restarts while clients are no longer waiting

### 4.2 File I/O Layer (`core/file_io.py`)

**Atomic Writes**:
- Write to a temporary file in the same directory (`.filename.tmp`)
- `fsync` the temp file
- Rename temp file to target (atomic on POSIX, near-atomic on Windows)
- On failure: clean up temp file

**Content Hashing**:
- SHA-256 hash of the full file content
- Hash is computed on every read and write
- Hash format: `sha256:<hex_digest>`
- Hash registry maintained in memory (and optionally persisted)

### 4.3 Diff Engine (`core/diff_engine.py`)

Computes the difference between two file versions for contention responses.

**JSON diff format** (structured, agent-friendly):
- List of change regions, each with type (`added`, `removed`, `modified`)
- Line numbers, old content, new content
- Context lines before/after each region (configurable, default: 3 lines)
- Summary with counts of lines added/removed/modified and regions changed

**Unified diff format** (standard, human-readable):
- Standard unified diff text (like `git diff`)
- Same summary metadata

**Implementation**: Use Python's `difflib` for computation. Custom formatting for the JSON output.

### 4.4 Path Validator (`core/path_validator.py`)

**Base Directory Enforcement**:
- Server configuration defines a list of allowed base directories
- All file paths in requests are resolved to absolute paths
- Resolved paths must be within at least one base directory
- Symlinks are resolved before validation (prevent symlink escape)
- Reject paths containing `..` traversal after resolution

### 4.5 Persistence Layer (`core/persistence.py`)

**Optional feature** (enabled via configuration).

**Persisted State**:
- File hash registry (path -> SHA-256 hash)
- Pending queue entries (serialized request metadata, not file content)

**Storage**: JSON file in the server's data directory (`{DATA_DIR}/state.json`)

**Startup Recovery**:
1. Load persisted state
2. Purge queue entries whose TTL has expired (prevents deadlocks from orphaned locks)
3. Re-validate file hashes against actual files on disk (detect external modifications)
4. Log discrepancies (hash mismatches from external edits)

**Write Strategy**: Debounced writes (at most once per second) to avoid I/O overhead from frequent state changes.

### 4.6 File Watcher (`core/file_watcher.py`)

Monitors base directories for external file modifications using OS-level filesystem events. This ensures the hash registry stays current when files are edited outside the MCP server (e.g., human editing in VS Code).

**Platform Implementation**:

| Platform | API | Library |
|----------|-----|---------|
| Windows | `ReadDirectoryChangesW` | `watchdog` (or direct ctypes) |
| macOS | `FSEvents` | `watchdog` |
| Linux | `inotify` | `watchdog` |

**Behavior**:
1. On server startup, register watchers for all configured `base_directories`
2. On file change event (create, modify, delete):
   - If the file is in the hash registry, re-read and update its hash
   - If the file was deleted, remove it from the hash registry
   - If the file is new (not in registry), ignore (it will be registered on first access)
3. Events are debounced (100ms) to handle editors that save via temp-file-then-rename

**Integration with contention**: When a human edits `file.py` in VS Code, the watcher updates the hash registry immediately. The next `async_update()` from an agent sees a hash mismatch and receives a standard contention response with diff. The agent does not need to know whether the change came from another agent or an external editor -- the resolution workflow is the same.

**Configuration**:

```json
{
  "watcher": {
    "enabled": true,
    "_enabled_help": "Enable OS filesystem watcher for external modification detection",
    "debounce_ms": 100,
    "_debounce_ms_help": "Debounce interval for filesystem events (editors save via rename)"
  }
}
```

**Dependency**: `watchdog>=4.0` (cross-platform filesystem monitoring)

### 4.7 Connection Lifecycle

MCP tool calls are blocking from the client's perspective -- the agent sends a request and waits for a response. The server-side lock manager holds the request in the FIFO queue until the lock is acquired or the timeout expires.

**Timeout and disconnection**:
- The `timeout` parameter on write operations defines how long the server will hold a request in the queue
- If the client disconnects before the server responds (e.g., agent process killed, network timeout), the server detects the closed connection and removes the pending request from the FIFO queue
- This prevents orphaned queue entries from blocking subsequent requests
- The server logs disconnection events for debugging: `"Client disconnected while waiting for lock on {path}"`

**Notification support** (future): The MCP specification supports server-to-client notifications. While Claude Code CLI does not currently consume MCP notifications, the server architecture is designed to support them when client support is available. Potential notification events:
- `file_changed`: A tracked file was modified (by another agent or externally)
- `lock_released`: A file the agent was waiting on is now available
- `queue_position`: Agent's position in the FIFO queue changed

These notifications are **not implemented in v0.1.0** but the event infrastructure (file watcher, lock state changes) produces the signals needed to emit them.

---

## 5. Configuration

Following the daemon-service template's `CONFIG.template.md` pattern with pydantic-settings:

```json
{
  "$schema": "https://example.com/schemas/async-crud-mcp.config.schema.json",
  "_version": "1.0",

  "daemon": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8720,
    "_port_help": "HTTP port. null = auto-assign based on username hash (8720-8819)",
    "transport": "sse",
    "_transport_help": "MCP transport: 'sse' (recommended) or 'stdio'",
    "log_level": "DEBUG",
    "config_poll_seconds": 3,
    "config_debounce_seconds": 1.0,
    "_config_debounce_seconds_help": "Minimum time between config reloads (prevents mid-write reads)",
    "session_poll_seconds": 3,
    "_session_poll_seconds_help": "How often bootstrap checks user login session state",
    "wait_for_session": true,
    "_wait_for_session_help": "Wait for active user session before starting MCP server",
    "health_check_interval": 30,
    "_health_check_interval_help": "Seconds between MCP server health checks"
  },

  "crud": {
    "base_directories": [],
    "_base_directories_help": "List of absolute paths. Only files within these directories can be accessed. Empty = reject all requests.",

    "default_timeout": 30.0,
    "_default_timeout_help": "Default lock timeout in seconds for write/update/delete operations",

    "max_timeout": 300.0,
    "_max_timeout_help": "Maximum allowed timeout per request",

    "default_encoding": "utf-8",

    "diff_context_lines": 3,
    "_diff_context_lines_help": "Lines of context before/after each diff region",

    "max_file_size_bytes": 10485760,
    "_max_file_size_bytes_help": "Maximum file size for read/write operations (10MB default)"
  },

  "persistence": {
    "enabled": false,
    "_enabled_help": "Enable state persistence across restarts",

    "state_file": null,
    "_state_file_help": "Path to state file. null = default location in DATA_DIR",

    "write_debounce_seconds": 1.0,

    "ttl_multiplier": 2.0,
    "_ttl_multiplier_help": "TTL for persisted entries = request timeout * this multiplier"
  },

  "watcher": {
    "enabled": true,
    "_enabled_help": "Enable OS filesystem watcher for external modification detection (inotify/ReadDirectoryChangesW/FSEvents)",

    "debounce_ms": 100,
    "_debounce_ms_help": "Debounce interval in ms for filesystem events (editors save via temp-file-then-rename)"
  }
}
```

**Environment variable overrides** (via pydantic-settings):
```
ASYNC_CRUD_MCP_DAEMON__PORT=8720
ASYNC_CRUD_MCP_CRUD__DEFAULT_TIMEOUT=60.0
ASYNC_CRUD_MCP_PERSISTENCE__ENABLED=true
```

---

## 6. Dependencies

```toml
[project]
name = "async-crud-mcp"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "typer>=0.9",
    "rich>=13.0",
    "loguru>=0.7",
    "tenacity>=8.0",
    "httpx>=0.24",
    "watchdog>=4.0",
    "python-dotenv>=1.0",
    "pywin32>=306; sys_platform == 'win32'",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-timeout>=2.0",
    "ruff>=0.4",
    "psutil>=5.9",
]
```

---

## 7. Error Handling

### 7.1 Error Code Registry

| Code | HTTP-Equivalent | Description |
|------|-----------------|-------------|
| `FILE_NOT_FOUND` | 404 | File does not exist |
| `FILE_EXISTS` | 409 | File already exists (async_write) |
| `ACCESS_DENIED` | 403 | OS-level permission denied |
| `PATH_OUTSIDE_BASE` | 403 | Path not within configured base directories |
| `LOCK_TIMEOUT` | 408 | Lock not acquired within timeout |
| `ENCODING_ERROR` | 400 | Cannot decode/encode with specified encoding |
| `INVALID_PATCH` | 400 | Patch old_string not found in file content |
| `CONTENT_OR_PATCHES_REQUIRED` | 400 | async_update requires either content or patches |
| `FILE_TOO_LARGE` | 413 | File exceeds max_file_size_bytes |
| `WRITE_ERROR` | 500 | OS-level write failure |
| `DELETE_ERROR` | 500 | OS-level delete failure |
| `RENAME_ERROR` | 500 | OS-level rename failure |
| `DIR_NOT_FOUND` | 404 | Directory does not exist (async_list) |
| `SERVER_ERROR` | 500 | Unexpected internal error |

### 7.2 Error Response Schema

All errors follow a consistent schema:

```json
{
  "status": "error",
  "error_code": "LOCK_TIMEOUT",
  "message": "Human-readable description",
  "path": "/abs/path/to/file.py",
  "details": {}
}
```

The `details` field is optional and may contain additional context (e.g., queue depth at timeout, current lock holder type).

---

## 8. Concurrency Model

### 8.1 Threading Model

The server uses Python's `asyncio` event loop with `asyncio.Lock` and `asyncio.Condition` for coordination:

- All MCP tool handlers are `async def`
- File I/O is delegated to a thread pool via `asyncio.to_thread()` to avoid blocking the event loop
- Lock acquisition uses `asyncio.wait_for()` with the caller's timeout

### 8.2 Fairness Guarantees

- FIFO ordering is enforced per-file: requests are queued in arrival order
- No priority inversion: a read cannot jump ahead of a queued write
- Starvation prevention: continuous reads cannot indefinitely block a pending write. Once a write request is queued, new read requests queue behind it.

### 8.3 Deadlock Prevention

- Single-file locks for CRUD operations: batch operations lock files sequentially, one at a time
- **Exception**: `async_rename()` acquires locks on two files simultaneously. Deadlock is prevented by always acquiring locks in alphabetical path order (consistent lock ordering).
- TTL on all exclusive locks: locks expire after `timeout` seconds
- No nested lock acquisition beyond the rename exception above
- Persisted locks have TTL expiry on server restart

---

## 9. Security

### 9.1 Path Validation

- All paths resolved to absolute paths before processing
- Symlink resolution before base directory check
- Reject `..` traversal
- Base directory whitelist enforced on every operation

### 9.2 Network

- Binds to `127.0.0.1` only (localhost, not exposed to network)
- No authentication (localhost-only model, same as other MCP servers)

### 9.3 File Content

- Text files only (no binary file support in this version)
- Maximum file size enforced (default 10MB)
- Content is never logged (only paths, hashes, and metadata)

---

## 10. Testing Strategy

### 10.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| `lock_manager` | Lock semantics, FIFO ordering, timeout, TTL expiry, dual-lock ordering (rename) |
| `file_io` | Atomic writes, hash computation, encoding, append operations |
| `diff_engine` | JSON diff, unified diff, edge cases (empty file, single line), patch applicability |
| `path_validator` | Base directory enforcement, symlink escape, traversal, directory listing |
| `file_watcher` | Event debouncing, hash registry update, create/modify/delete events |
| `persistence` | Save/load state, TTL purge on restart |

### 10.2 Integration Tests

| Scenario | Description |
|----------|-------------|
| Concurrent reads | Multiple simultaneous reads on same file succeed without blocking |
| Read-write contention | Read completes, write queues, next read queues behind write |
| Write-write contention | Two writes on same file: FIFO order, second gets contention diff |
| Timeout | Write request times out while waiting for lock |
| Client disconnect | Client disconnects mid-wait; server removes pending request from queue |
| Diff accuracy | Verify diff correctly reflects changes between versions |
| Patch applicability | Contention response correctly reports which patches can still apply |
| Rename atomicity | Concurrent rename + read on same file; dual-lock ordering prevents deadlock |
| Append concurrency | Multiple concurrent appends produce correct combined output |
| Directory listing | async_list returns current state including recently created files |
| External modification | File edited outside server; watcher updates hash; next update gets contention |
| Persistence round-trip | Server restart with pending queue; TTL purge; hash re-validation |
| Batch operations | Multiple files in single request, partial failures (read/write/update) |

### 10.3 Stress Tests (future)

- 10+ concurrent agents with overlapping file access
- Large files (approaching max_file_size_bytes)
- Rapid lock acquire/release cycles

---

## 11. Client Integration

### 11.1 Claude Desktop / Claude Code CLI

Add to Claude Desktop's MCP configuration:

```json
{
  "mcpServers": {
    "async-crud-mcp": {
      "type": "sse",
      "url": "http://localhost:8720/sse"
    }
  }
}
```

**Configuration file locations**:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

The `scripts/configure_claude_code.py` snippet handles this automatically during `setup`.

### 11.2 HTTP Health Endpoint

The MCP server exposes a non-MCP health endpoint for service monitoring:

```
GET /health
Response: {"status": "healthy", "version": "0.1.0", "uptime_seconds": 3600, "port_listening": true}
```

This is used by:
- The bootstrap service's health check polling (every `health_check_interval` seconds)
- The CLI `daemon status` command
- The dispatcher's runtime TCP health check (ADR-012)
- Post-install verification (`test_server.py`)

### 11.3 Dynamic Port Assignment

When `daemon.port` is set to `null`, the server assigns a port deterministically by username hash:

```python
def get_user_port(username: str, base_port: int = 8720, range_size: int = 100) -> int:
    username_lower = username.lower()
    hash_bytes = hashlib.sha256(username_lower.encode()).digest()
    offset = int.from_bytes(hash_bytes[:2], 'big') % range_size
    return base_port + offset
```

Port range: `8720-8819` (registered in daemon-service port assignment SSOT as "Custom").

If the default port (8720) is already in use at startup, the `config_init.find_available_port()` function scans upward to find the next free port in the range.

---

## 12. Logging Architecture

### 12.1 Loguru Standard (MANDATORY per PYTHON_STACK.template.md)

All logging MUST use loguru with `enqueue=True` for thread/async safety (ADR-005):

```python
from loguru import logger

logger.add(log_file, enqueue=True, rotation="10 MB", retention="7 days",
           compression="gz", serialize=True)
```

**Shutdown drain** (MANDATORY): `await logger.complete()` in every `finally` block before process exit. Without this, enqueued log messages are lost.

### 12.2 Logging Fallback Chain (Windows Service Context)

When running as a Windows service (LocalSystem), `%LOCALAPPDATA%` points to `systemprofile` (ADR-006). The dispatcher uses a three-level fallback:

1. `%PROGRAMDATA%\async-crud-mcp\logs\` (preferred for system service)
2. `%LOCALAPPDATA%\async-crud-mcp\logs\` (fallback)
3. `%TEMP%\async-crud-mcp\logs\` (last resort)

Each level: attempt `mkdir`, write test file, verify writable.

### 12.3 Anti-Patterns

- `import logging` (stdlib) -- use `from loguru import logger`
- `print()` for debugging -- use `logger.debug()`
- Missing `enqueue=True` in async code -- causes race conditions
- Missing `await logger.complete()` before exit -- loses queued messages
- `diagnose=True` in production -- leaks variable values

---

## 13. Implementation Guardrails

Critical bugs and architectural decisions from the daemon-service template's production history (v1.13.0 + v1.14.0). These MUST be incorporated during implementation.

### 13.1 Windows Service Bugs (CRITICAL)

| Bug | Symptom | Fix |
|-----|---------|-----|
| **BUG-01** | Error 1053 "service did not respond in a timely fashion" | Call `self.ReportServiceStatus(win32service.SERVICE_RUNNING)` as FIRST line of `SvcDoRun()` |
| **BUG-02/10** | `ValueError: signal only works in main thread` | Do NOT use `asyncio.run()` in service context. Use `WindowsSelectorEventLoopPolicy` + manual event loop (ADR-011) |
| **BUG-03** | `sys.executable` returns `pythonservice.exe`, not `python.exe` | Multi-candidate search: `sys.prefix/Scripts`, `venv/Scripts`, `exe_dir` (ADR-007) |
| **BUG-04** | Service hangs/freezes after running | subprocess.PIPE 64KB buffer deadlock. Use `subprocess.DEVNULL` or redirect to log file |
| **BUG-07** | Service crashes with no application logs | Wrap ALL `SvcDoRun()` logic in try/except. Use `servicemanager.LogErrorMsg()` as backstop |

### 13.2 Windows Service Event Loop Pattern (ADR-011)

```python
def SvcDoRun(self):
    self.ReportServiceStatus(win32service.SERVICE_RUNNING)  # BUG-01: FIRST

    try:
        # ADR-011: Manual event loop for non-main thread
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.main())
        finally:
            loop.close()
    except Exception as e:
        servicemanager.LogErrorMsg(f"Service failed: {e}")  # BUG-07
```

### 13.3 pywin32 DLL Setup (BUG-08)

The installer MUST explicitly copy these files for `pythonservice.exe` to function:

| File | Source | Destination |
|------|--------|-------------|
| `pythonservice.exe` | `site-packages/win32/` | venv `Scripts/` |
| `python3XX.dll` | Python base | venv root |
| `pythoncom3XX.dll` | `site-packages/pywin32_system32/` | venv root |
| `pywintypes3XX.dll` | `site-packages/pywin32_system32/` | venv root |
| `python3XX._pth` | Generated | venv root (points to `Lib/site-packages` and `Lib`) |

### 13.4 Service Installation (BUG-11)

Do NOT use `win32serviceutil.HandleCommandLine()` for programmatic service install -- it prints to stdout and calls `sys.exit(1)` instead of raising exceptions. Use direct `win32service.CreateService()` + `winreg.CreateKeyEx()` for the `PythonClass` registry entry.

### 13.5 Port Conflict Detection (ADR-012)

Three-layer defense against orphaned processes holding the port:

1. **Server pre-flight**: `socket.bind()` test before `mcp.run()`. Exit code 48 on conflict. Required because uvicorn catches `OSError(10048)` internally and exits cleanly -- the error never propagates to application code.

2. **Dispatcher pre-start**: Before `CreateProcessAsUser`, check port. Kill orphan via `_kill_port_owner()`. Re-check. Abort if still blocked.

3. **Runtime health poll**: After `exit_code == STILL_ACTIVE`, also check `_is_port_listening()`. Startup grace period (15s) avoids false positives. If alive but not listening, restart worker.

### 13.6 Path and Naming (BUG-09, ADR-009)

Use SINGLE `APP_NAME` constant (`async-crud-mcp`, lowercase-hyphenated) for ALL purposes: directory names, service names, log prefixes, config keys, display text. NEVER create separate display/lower variants -- this caused production path mismatch bugs.

### 13.7 Config Resilience

**Debounce**: Config reads must be debounced (default 1.0s) to prevent reading partial JSON during editor mid-write saves. Use `ConfigWatcher` from `config_watcher.py`.

**Last-known-good**: Cache the last valid config. On validation failure, fall back to cached config instead of crashing. Use `ResilientConfigLoader` pattern from `CONFIG.template.md`.

### 13.8 Installer Constraints

- `scripts/installer.py` MUST use ONLY Python stdlib modules (runs before any packages are installed)
- Use `uv venv --managed-python` for stable venvs independent of installer Python (ADR-010)
- Three-stage architecture: shell wrapper -> stdlib installer -> rich CLI setup

### 13.9 Subprocess Management (BUG-04, BUG-13)

- NEVER use `subprocess.PIPE` for stderr/stdout without actively draining. Use `subprocess.DEVNULL` or redirect to file.
- Use `CREATE_NEW_PROCESS_GROUP` flag on Windows so the entire child tree can be terminated.
- On startup, check for and clean up stale processes holding the port.

---

## 14. Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | Should `async_update()` support partial file patching (e.g., line-range edits) in addition to `old_string`/`new_string` pairs? | Deferred to v0.2.0 |
| 2 | Should the server support watching directories for external file changes (inotify/ReadDirectoryChangesW)? | **Resolved**: Yes, via `watchdog` library. See Section 4.6 File Watcher. OS-level filesystem events update hash registry in real-time. External edits trigger standard contention responses. |
| 3 | Port assignment: is 8720 available in the daemon-service port registry? | **Resolved**: Using 8720 in Custom range (8720+) per port-assignment SSOT |
| 4 | Should batch operations support mixing read and write in a single call? | Deferred to v0.2.0 |

---

## 15. References

- **Daemon Service Template**: `C:\Users\Admin\Documents\GitHub\claude-code-tooling\claude-mcp\daemon-service\`
  - Templates: `OVERVIEW`, `BOOTSTRAP`, `SERVICE`, `CONFIG`, `PYTHON_STACK`, `INSTALLER`, `CLI_COMMANDS`, `INTEGRATION`
  - Snippets: `common/`, `windows/`, `scripts/`
- **FastMCP**: https://github.com/jlowin/fastmcp
- **MCP Specification**: https://modelcontextprotocol.io/
- **Python asyncio locks**: https://docs.python.org/3/library/asyncio-sync.html
