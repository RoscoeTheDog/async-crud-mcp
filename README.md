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
│ • FastMCP-based server exposing 11 CRUD tools:             │
│   - write, read, update, delete, append, rename            │
│   - list, status, batch_write, batch_read, batch_update    │
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

## License

[MIT](LICENSE)
