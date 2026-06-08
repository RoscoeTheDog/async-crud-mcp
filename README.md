# async-crud-mcp

A Python daemon MCP (Model Context Protocol) server built with [FastMCP](https://github.com/jlowin/fastmcp) that provides file-locking async CRUD operations designed for concurrent AI agent use.

## Overview

This server exposes Create, Read, Update, and Delete tools over MCP with built-in file-locking to safely handle concurrent access from multiple AI agents. It runs as a persistent daemon process, supporting both stdio and HTTP (Streamable HTTP) transports.

## Features

- Async file-locking CRUD operations
- Safe concurrent access for multiple AI agents
- FastMCP-based MCP server (Python 3.12+)
- Stdio and HTTP transport support
- Daemon process mode with bootstrap service management
- Platform-specific service integration (Windows Service/Task Scheduler, macOS launchd, Linux systemd)

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (optional for manual install)

### Quick Install (Recommended)

Platform-specific setup scripts auto-detect Python 3.12+ and handle installation:

**Windows:**
```bash
scripts\setup.bat
```

**macOS/Linux:**
```bash
scripts/setup.sh
```

The scripts automatically:
1. Detect Python 3.12+ installation
2. Install dependencies using `uv`
3. Delegate to `installer.py` for full configuration

### Post-Install One-Liner

After installation, run the interactive setup wizard or use quick-install:

```bash
async-crud-mcp quick-install --yes
```

### Manual Install

If you prefer manual installation using `uv`:

```bash
# Clone the repository
git clone https://github.com/RoscoeTheDog/async-crud-mcp.git
cd async-crud-mcp

# Install dependencies
uv sync

# Run the server
uv run async-crud-mcp
```

## Usage

### Setup Wizard (Interactive)

Start the interactive setup wizard to configure the MCP server:

```bash
async-crud-mcp setup
```

The wizard prompts for:
- Port number (default: 3000)
- Host address (default: localhost)
- Transport protocol (stdio/sse)
- Log level (DEBUG/INFO/WARNING/ERROR)
- Daemon installation option

### Quick Install (Non-Interactive)

Full setup with sensible defaults:

```bash
# Install with defaults
async-crud-mcp quick-install --yes

# Custom port
async-crud-mcp quick-install --yes --port 8000

# Force reinstall
async-crud-mcp quick-install --yes --force

# Install without starting daemon
async-crud-mcp quick-install --yes --no-start
```

### Uninstall

Stop and remove the daemon:

```bash
# Interactive uninstall
async-crud-mcp uninstall

# Non-interactive with config removal
async-crud-mcp uninstall --yes --remove-config

# Remove logs too
async-crud-mcp uninstall --yes --remove-config --remove-logs
```

### Configuration Management

Manage configuration with the `config` command group:

```bash
# Initialize new config
async-crud-mcp config init

# Force overwrite existing config
async-crud-mcp config init --force --port 9000

# Show current config
async-crud-mcp config show

# Show config in JSON format
async-crud-mcp config show --json

# Edit config interactively
async-crud-mcp config edit

# Validate config file
async-crud-mcp config validate

# Validate specific username
async-crud-mcp config validate --username admin
```

### Daemon Lifecycle

Control the MCP server daemon:

```bash
# Start daemon
async-crud-mcp daemon start

# Start in background (detached)
async-crud-mcp daemon start --background

# Stop daemon
async-crud-mcp daemon stop

# Restart daemon
async-crud-mcp daemon restart

# Check daemon status
async-crud-mcp daemon status

# View daemon logs
async-crud-mcp daemon logs

# Follow logs in real-time
async-crud-mcp daemon logs --follow
```

### Bootstrap Service Management

Manage platform-specific service integration:

```bash
# Install bootstrap service
async-crud-mcp bootstrap install

# Force reinstall
async-crud-mcp bootstrap install --force

# Install with specific username (Unix)
async-crud-mcp bootstrap install --username myuser

# Use Windows Task Scheduler (instead of Service)
async-crud-mcp bootstrap install --use-task-scheduler

# Uninstall bootstrap service
async-crud-mcp bootstrap uninstall

# Start/stop bootstrap service
async-crud-mcp bootstrap start
async-crud-mcp bootstrap stop

# Check bootstrap status
async-crud-mcp bootstrap status

# List all bootstrap services
async-crud-mcp bootstrap list

# List in JSON format
async-crud-mcp bootstrap list --json
```

## Architecture

### Two-Layer Design

The `async-crud-mcp` project uses a two-layer architecture for robust daemon management:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Bootstrap Daemon (daemon/bootstrap_daemon.py)     │
│ ----------------------------------------------------------- │
│ • Monitors user session state and config changes           │
│ • Manages MCP server process lifecycle (start/stop/restart)│
│ • Platform-specific service integration:                   │
│   - Windows: Service or Task Scheduler                     │
│   - macOS: launchd                                          │
│   - Linux: systemd                                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: MCP Server (server.py)                            │
│ ----------------------------------------------------------- │
│ • FastMCP-based server exposing 26 MCP tools (see the          │
│   "Tools" section below): CRUD, batch, transactional           │
│   edits, recycle-bin, shell/search, status, config             │
│ • Supports SSE and stdio transports                         │
│ • Shared core components:                                   │
│   - PathValidator: Safe path resolution                     │
│   - LockManager: File-locking for concurrent access         │
│   - HashRegistry: Content integrity tracking                │
└─────────────────────────────────────────────────────────────┘
```

### Per-User Daemon Model

On **Windows**, `async-crud-mcp` uses a single system-wide Bootstrap service combined with a
`MultiUserDispatcher` (ADR-008). The dispatcher maintains a username-keyed map of MCP worker
processes and spawns each worker via `CreateProcessAsUser` for full process-level isolation:

- Each user gets a dedicated worker process with its own port (derived from a username hash, base 8400)
- Per-user config (`~/.async-crud-mcp/config.toml`) and log files are isolated per user account
- Workers start on session logon and stop only when the user's **last** active session ends
- The system-wide service itself runs as `LocalSystem` and never accesses user files directly

On **macOS**, the Bootstrap daemon runs as a **launchd user agent** (`~/Library/LaunchAgents/`),
launched automatically for each logged-in user by launchd — no system-wide service or dispatcher needed.

On **Linux**, the daemon runs as a **systemd user service** (`~/.config/systemd/user/`), activated
per-user by `systemd --user` — each user manages their own daemon instance independently.

### Supporting Subsystems

- **Configuration Management**: Pydantic Settings with TOML support
- **Health Checks**: Readiness and liveness endpoints
- **Graceful Shutdown**: Clean resource cleanup on termination
- **Config File Watcher**: Auto-reload on configuration changes
- **Session Detection**: Platform-specific session state monitoring
- **Structured Logging**: loguru-based logging with rotation

### Key Modules

- `daemon/bootstrap_daemon.py` - Bootstrap daemon process
- `daemon/installer.py` - Platform-specific service installer
- `server.py` - FastMCP server with CRUD tools
- `config.py` - Configuration management (Pydantic)
- `cli/` - CLI command groups (setup, daemon, config, bootstrap, quick-install/uninstall)

## Tools

The server exposes **26 MCP tools** across seven categories. The names below are
the server-side tool names; MCP clients see them prefixed (e.g.
`mcp__async-crud-mcp__async_read_tool`).

| Category | Tools |
|----------|-------|
| **File CRUD** | `async_read_tool`, `async_write_tool`, `async_update_tool`, `async_delete_tool`, `async_rename_tool`, `async_append_tool`, `async_mkdir_tool`, `async_list_tool` |
| **Batch** | `async_batch_read_tool`, `async_batch_write_tool`, `async_batch_update_tool` |
| **Transactional edits** | `async_query_replace_tool`, `async_commit_tool`, `async_amend_tool`, `async_abort_tool`, `async_txn_status_tool` |
| **Recycle bin** | `async_restore_tool`, `async_recycle_list_tool`, `async_recycle_clean_tool` |
| **Shell / search** | `async_exec_tool`, `async_wait_tool`, `async_search_tool` |
| **Status / health** | `async_status_tool`, `health_tool` |
| **Config / project** | `crud_activate_project`, `crud_get_config`, `crud_update_config` |

> Most non-exempt tools require a project to be activated first via
> `crud_activate_project`; calls before activation fail with a structured
> `NO_PROJECT_ACTIVATED` error so an agent can detect and self-activate.

### Editing model: read-then-edit and the dual-state hazard

`async_update_tool` uses **optimistic concurrency control**: `expected_hash` is a
required argument, supplied from a prior `async_read_tool`. The server tracks
content integrity in a `HashRegistry`; if the file changed since your read, the
update is rejected rather than silently clobbering a concurrent agent's write.
The flow is:

1. `async_read_tool(path)` → returns content **and** its content hash.
2. `async_update_tool(path, ..., expected_hash=<hash>)` → applies only if the
   file still matches; otherwise it returns a contention/hash-mismatch response —
   re-read and retry.

For broad or risky multi-match edits, prefer the **transactional tools**
(`async_query_replace_tool` → `async_commit_tool`), which generalize this manual
hash dance into a staged query→commit transaction: a diff preview, a server-side
compare-and-swap at commit time, and `async_amend_tool` / `async_abort_tool` to
adjust or discard staged changes.

A **subset commit keeps the transaction open** with the unapplied matches still
staged; commit is **all-or-nothing**, so a successful `async_commit_tool` applies
exactly the matches you requested and returns them in `applied_match_ids` (plus
`remaining_match_ids`, `ignored_match_ids` for requested ids no longer staged, and
`ttl_remaining`). To decide the next step without re-querying (which would start a
fresh transaction and re-scan the file), call the read-only `async_txn_status_tool`:
it relocates each still-staged match against the current file and reports its live
position and a `locatable` flag that predicts whether the next commit would apply
it or report it stale. Reported positions are an optimistic snapshot — only the
commit-time compare-and-swap is authoritative.

**Dual file-state rule.** Claude's native `Edit` tracks its own
read-before-edit state, and this server tracks its own via `HashRegistry`. On any
given file, use **either** the server's tools **or** native tools for a single
mutation sequence — do not interleave them mid-edit. The commit-time CAS will
catch a native write that lands between query and commit, but mixing the two
mid-sequence invites avoidable hash-mismatch churn.

**Stale-conflict and rebase contract.** At commit the server re-reads the file.
If it is unchanged since the query, staged matches apply at their captured
offsets. If it changed, each selected match is *relocated* by a **content
anchor** — the matched text plus roughly 48 characters of surrounding context.
A match applies only if that anchor (or, failing that, the matched text itself)
occurs **exactly once** in the new content; any ambiguity marks it stale, and if
any selected match is stale the entire commit is refused as `stale_conflict`
(nothing is written) — re-query to refresh. Practical consequence: a
"non-overlapping" external edit auto-rebases cleanly only when it lands
**outside the ~48-character window** of every match *and* the matched text stays
uniquely locatable. Editing close to a match, or replacing a token that recurs
elsewhere, conservatively triggers `stale_conflict` rather than risk a
wrong-position edit. A **subset commit** keeps the transaction open with the
remaining (unapplied) matches; they commit later through this same rebase path,
and the staged set is never re-scanned, so a replacement that introduces new
pattern occurrences never expands the transaction.

**Egress redaction and the write-back guard.** Reads, searches, transaction
previews, and shell output are scanned, and any secret-looking span is replaced
with a `<<REDACTED:rule:id>>` placeholder before leaving the daemon — the
response still carries the file's **real** hash, so read-then-edit CAS keeps
working. Because a read returns *redacted* text, writing that text straight back
would persist the placeholder and destroy the real secret. The full-content
write paths (`async_write_tool`, `async_update_tool` content mode, and their
batch forms) therefore **reject** content containing a redaction placeholder
with a `REDACTION_MARKERS_PRESENT` error. Edit via **patches**
(`patches` / `regex_patches`) — which carry only the changed snippets and are the
recommended path — or pass `allow_redaction_markers=true` for the rare file that
legitimately contains that literal text.

**Search vs. list scoping.** `async_search_tool` honors `search.exclude_dirs`
(e.g. `.async-crud-mcp`, `.git`, `node_modules`) and never returns matches from
them, so deleted secrets sitting in the recycle bin are not re-found by content
search. `async_list_tool` is a **metadata-only** directory listing and does
**not** apply `exclude_dirs`: a recursive list enumerates those directories'
entries (names and sizes only — never file content).

## License

[MIT](LICENSE)
