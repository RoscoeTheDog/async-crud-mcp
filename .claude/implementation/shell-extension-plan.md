# async-crud-mcp Shell Extension Implementation Plan

**Date**: 2026-02-19 | **Status**: Draft | **Branch**: TBD (feature/shell-extension)
**Prerequisite**: async-crud-mcp v0.1.0 (current) with 11 CRUD + 3 admin tools operational

---

## 1. Executive Summary

Extend the existing async-crud-mcp MCP server (port 8720) with **managed shell execution**, **timed blocking waits**, and **content search** capabilities. This transforms the server from a file-only CRUD layer into a complete agent execution environment where all file I/O AND shell commands go through a single controlled gateway with server-side policy enforcement.

**Why**: Claude Code subagents dispatched via `/context:TASK` currently have access to native Bash, which lets them bypass MCP CRUD tools (cat, echo >, sed, etc.). Denying native Bash but providing `async_exec_tool` with a server-side denylist gives subagents shell access for legitimate operations (pytest, git, npm) while blocking file I/O commands that should go through the CRUD tools.

**Scope**: 3 new tools, 2 new config models, 6 new request/response models, tests

---

## 2. Architecture

### 2.1 Current State

```
src/async_crud_mcp/
  __init__.py              # __version__
  __main__.py              # CLI entrypoint
  config.py                # Settings, DaemonConfig, CrudConfig, ProjectConfig, PathRule, ContentRule
  server.py                # FastMCP: 11 CRUD + health/config/activate tools, middleware
  cli/                     # CLI commands (bootstrap, config, daemon, install, setup)
  core/                    # PathValidator, LockManager, HashRegistry, ContentScanner, FileIO, DiffEngine, Persistence, FileWatcher
  tools/                   # 11 tool modules (async_read, async_write, async_update, async_delete, async_rename, async_append, async_list, async_status, async_batch_read, async_batch_write, async_batch_update)
  models/                  # requests.py (11 request + 3 batch item models), responses.py (11 response models)
  daemon/                  # Windows service, config watcher, health, dispatcher, paths, logging, installer, session_detector
```

**Key patterns to follow**:
- Tools are thin `@mcp.tool()` wrappers in `server.py` that delegate to `tools/` modules
- Request models in `models/requests.py` (Pydantic BaseModel, strict typing)
- Response models in `models/responses.py` (frozen=True, Literal status fields)
- `ProjectActivationMiddleware` requires project activation before CRUD tools
- Config sections are Pydantic BaseModel nested inside `Settings(BaseSettings)`
- Per-project overrides via `.async-crud-mcp/config.json` -> `ProjectConfig`
- Hot-reload via `ConfigWatcher` watching `.async-crud-mcp/config.json`

### 2.2 Target State

```
src/async_crud_mcp/
  config.py                # + ShellConfig, ShellDenyPattern, SearchConfig
  server.py                # + 3 new @mcp.tool() wrappers, shell_validator module-level
  tools/
    async_exec.py          # NEW: managed shell execution
    async_wait.py          # NEW: timed blocking wait + task polling
    async_search.py        # NEW: regex content search
  models/
    requests.py            # + ExecRequest, WaitRequest, SearchRequest
    responses.py           # + ExecSuccessResponse, ExecDeniedResponse, ExecBackgroundResponse, WaitResponse, SearchResponse + ErrorCodes
  core/
    shell_validator.py     # NEW: denylist pattern matching engine
    background_tasks.py    # NEW: background task tracking (for exec background mode)
```

---

## 3. Detailed Design

### 3.1 Config Models (`config.py`)

#### ShellDenyPattern

```python
class ShellDenyPattern(BaseModel):
    """A pattern that blocks specific shell commands."""
    pattern: str = Field(..., description="Regex pattern to match against command string")
    reason: str = Field(default="", description="Human-readable reason shown to agent on deny")
```

#### ShellConfig

```python
class ShellConfig(BaseModel):
    """Shell execution configuration section."""
    enabled: bool = False  # OFF by default - opt-in per project
    deny_patterns: list[ShellDenyPattern] = Field(default_factory=_default_deny_patterns)
    max_command_length: int = 10000
    timeout_default: float = 120.0
    timeout_max: float = 600.0
    env_inherit: bool = True
    env_strip: list[str] = Field(default_factory=lambda: ["CLAUDECODE"])
    cwd_override: str | None = None  # None = use project root
```

#### SearchConfig

```python
class SearchConfig(BaseModel):
    """Content search configuration section."""
    enabled: bool = True
    max_results: int = 1000
    max_file_size_bytes: int = 10_485_760  # 10MB (match CrudConfig)
    timeout_default: float = 30.0
```

#### Default Deny Patterns

```python
def _default_deny_patterns() -> list[ShellDenyPattern]:
    return [
        # ---- File READ bypass ----
        ShellDenyPattern(pattern=r'\bcat\b', reason="Use async_read_tool instead"),
        ShellDenyPattern(pattern=r'\bhead\b', reason="Use async_read_tool with limit instead"),
        ShellDenyPattern(pattern=r'\btail\b', reason="Use async_read_tool with offset instead"),
        ShellDenyPattern(pattern=r'\bless\b', reason="Use async_read_tool instead"),
        ShellDenyPattern(pattern=r'\bmore\b', reason="Use async_read_tool instead"),
        # ---- File WRITE bypass ----
        ShellDenyPattern(pattern=r'\btee\b', reason="Use async_write_tool instead"),
        ShellDenyPattern(pattern=r'\bsed\b', reason="Use async_update_tool with patches instead"),
        ShellDenyPattern(pattern=r'\bawk\b', reason="Use async_read_tool + parse instead"),
        ShellDenyPattern(pattern=r'\becho\b.*[>|]', reason="Use async_write_tool instead"),
        ShellDenyPattern(pattern=r'\bprintf\b.*[>|]', reason="Use async_write_tool instead"),
        # ---- File COPY/MOVE/DELETE bypass ----
        ShellDenyPattern(pattern=r'\bcp\b', reason="Use async_read_tool + async_write_tool instead"),
        ShellDenyPattern(pattern=r'\bmv\b', reason="Use async_rename_tool instead"),
        ShellDenyPattern(pattern=r'\brm\b', reason="Use async_delete_tool instead"),
        ShellDenyPattern(pattern=r'\bdd\b', reason="Blocked: raw disk operations not allowed"),
        ShellDenyPattern(pattern=r'\btouch\b', reason="Use async_write_tool with empty content"),
        ShellDenyPattern(pattern=r'\bmkdir\b', reason="Use async_write_tool with create_dirs=true"),
        # ---- Content SEARCH bypass ----
        ShellDenyPattern(pattern=r'\bgrep\b', reason="Use async_search_tool instead"),
        ShellDenyPattern(pattern=r'\brg\b', reason="Use async_search_tool instead"),
        ShellDenyPattern(pattern=r'\bfind\b', reason="Use async_list_tool with recursive=true instead"),
        ShellDenyPattern(pattern=r'\bls\b', reason="Use async_list_tool instead"),
        # ---- Anti-circumvention (language-level file I/O) ----
        ShellDenyPattern(pattern=r'python.*-c.*open\(', reason="Use async-crud-mcp tools for file I/O"),
        ShellDenyPattern(pattern=r'node.*-e.*fs\.', reason="Use async-crud-mcp tools for file I/O"),
    ]
```

#### ProjectConfig Extension

Add to existing `ProjectConfig`:

```python
class ProjectConfig(BaseModel):
    # ... existing fields ...
    shell_enabled: bool | None = None          # None = use global default
    shell_deny_patterns: list[ShellDenyPattern] = Field(default_factory=list)
    shell_deny_patterns_mode: Literal["extend", "replace", "disable"] = "extend"
```

#### Settings Extension

Add to existing `Settings`:

```python
class Settings(BaseSettings):
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    crud: CrudConfig = Field(default_factory=CrudConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)
    shell: ShellConfig = Field(default_factory=ShellConfig)     # NEW
    search: SearchConfig = Field(default_factory=SearchConfig)   # NEW
```

### 3.2 Core: Shell Validator (`core/shell_validator.py`)

```python
"""Server-side command validation against deny patterns.

Compiles regex patterns once at init. Re-compiles on config hot-reload.
"""

import re
from async_crud_mcp.config import ShellDenyPattern

class ShellValidator:
    """Validates shell commands against a compiled denylist."""

    def __init__(self, deny_patterns: list[ShellDenyPattern]):
        self._patterns: list[tuple[re.Pattern, str]] = []
        self.reload(deny_patterns)

    def reload(self, deny_patterns: list[ShellDenyPattern]) -> None:
        """Recompile patterns (called on config hot-reload)."""
        self._patterns = [
            (re.compile(p.pattern), p.reason) for p in deny_patterns
        ]

    def validate(self, command: str) -> tuple[bool, str]:
        """Check command against denylist.

        Returns:
            (True, "") if command is allowed
            (False, reason) if command is denied
        """
        for pattern, reason in self._patterns:
            if pattern.search(command):
                return False, reason
        return True, ""
```

### 3.3 Core: Background Tasks (`core/background_tasks.py`)

```python
"""Track background subprocess tasks for async_exec_tool(background=True)."""

import asyncio
from dataclasses import dataclass, field

@dataclass
class BackgroundTask:
    task_id: str
    process: asyncio.subprocess.Process
    stdout_buffer: list[str] = field(default_factory=list)
    stderr_buffer: list[str] = field(default_factory=list)
    exit_code: int | None = None
    started_at: float = 0.0
    completed_at: float | None = None
    completion_event: asyncio.Event = field(default_factory=asyncio.Event)

class BackgroundTaskRegistry:
    """Registry for tracking background exec tasks."""

    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}

    def register(self, task: BackgroundTask) -> None: ...
    def get(self, task_id: str) -> BackgroundTask | None: ...
    def remove(self, task_id: str) -> None: ...
    def list_active(self) -> list[str]: ...
    async def wait_for(self, task_id: str, timeout: float) -> BackgroundTask | None: ...
```

### 3.4 Request Models (`models/requests.py`)

```python
class ExecRequest(BaseModel):
    """Request model for async_exec tool."""
    command: str = Field(..., description="Shell command to execute", max_length=10000)
    timeout: float = Field(default=120.0, description="Timeout in seconds", ge=0.1, le=600.0)
    cwd: str | None = Field(default=None, description="Working directory (default: project root)")
    env: dict[str, str] | None = Field(default=None, description="Additional environment variables")
    background: bool = Field(default=False, description="Run in background, return task_id immediately")

class WaitRequest(BaseModel):
    """Request model for async_wait tool."""
    seconds: float = Field(default=120.0, description="Duration to wait", ge=0.1, le=600.0)
    task_id: str | None = Field(default=None, description="Background task ID to wait for")

class SearchRequest(BaseModel):
    """Request model for async_search tool."""
    pattern: str = Field(..., description="Regex pattern to search for")
    path: str | None = Field(default=None, description="Directory or file to search (default: project root)")
    glob: str = Field(default="*", description="Glob pattern to filter files")
    recursive: bool = Field(default=True, description="Search recursively")
    case_insensitive: bool = Field(default=False, description="Case insensitive search")
    max_results: int = Field(default=100, description="Maximum results to return", ge=1, le=1000)
    context_lines: int = Field(default=0, description="Lines of context around matches", ge=0, le=10)
    output_mode: Literal["files_with_matches", "content", "count"] = Field(default="files_with_matches")
```

### 3.5 Response Models (`models/responses.py`)

```python
# New error codes to add to ErrorCode enum
class ErrorCode(StrEnum):
    # ... existing codes ...
    COMMAND_DENIED = "COMMAND_DENIED"         # Shell denylist match
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"       # Exec timeout
    SHELL_DISABLED = "SHELL_DISABLED"         # Shell not enabled for project
    SEARCH_DISABLED = "SEARCH_DISABLED"       # Search not enabled
    TASK_NOT_FOUND = "TASK_NOT_FOUND"         # Background task ID not found
    INVALID_PATTERN = "INVALID_PATTERN"       # Bad regex pattern


class ExecSuccessResponse(BaseModel):
    """Success response for async_exec tool (foreground)."""
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    command: str = Field(..., description="Command that was executed")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    exit_code: int = Field(..., description="Process exit code")
    duration_ms: float = Field(..., description="Execution duration in milliseconds")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class ExecDeniedResponse(BaseModel):
    """Denied response when command matches denylist."""
    model_config = ConfigDict(frozen=True)

    status: Literal["denied"] = "denied"
    command: str = Field(..., description="Command that was denied")
    matched_pattern: str = Field(..., description="Denylist pattern that matched")
    reason: str = Field(..., description="Human-readable guidance for the agent")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class ExecBackgroundResponse(BaseModel):
    """Background response for async_exec tool."""
    model_config = ConfigDict(frozen=True)

    status: Literal["background"] = "background"
    task_id: str = Field(..., description="Background task ID for polling")
    command: str = Field(..., description="Command running in background")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class WaitResponse(BaseModel):
    """Response for async_wait tool."""
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    waited_seconds: float = Field(..., description="Actual seconds waited")
    reason: Literal["timeout", "task_completed", "task_failed"] = Field(..., description="Why wait ended")
    task_result: ExecSuccessResponse | None = Field(default=None, description="Task result if waited for task_id")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")


class SearchMatch(BaseModel):
    """A single search match."""
    model_config = ConfigDict(frozen=True)

    file: str = Field(..., description="File path containing match")
    line_number: int | None = Field(default=None, description="Line number of match")
    line_content: str | None = Field(default=None, description="Matching line content")
    context_before: list[str] | None = Field(default=None, description="Lines before match")
    context_after: list[str] | None = Field(default=None, description="Lines after match")


class SearchResponse(BaseModel):
    """Response for async_search tool."""
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    pattern: str = Field(..., description="Search pattern used")
    matches: list[SearchMatch] = Field(..., description="Search matches")
    total_matches: int = Field(..., description="Total matches found (may exceed max_results)")
    files_searched: int = Field(..., description="Number of files searched")
    output_mode: str = Field(..., description="Output mode used")
    truncated: bool = Field(default=False, description="Whether results were truncated")
    timestamp: str = Field(..., description="Operation timestamp (ISO 8601)")
```

### 3.6 Tool Implementations

#### `tools/async_exec.py`

Core logic:
1. Validate `shell.enabled` (return SHELL_DISABLED if false)
2. Validate command length against `max_command_length`
3. Run command through `ShellValidator.validate()` (return ExecDeniedResponse on match)
4. Clamp timeout to `[0.1, timeout_max]`
5. Resolve cwd: explicit `cwd` > `shell.cwd_override` > `_active_project_root`
6. Build environment: `os.environ.copy()` if `env_inherit`, strip `env_strip` keys, merge `env` param
7. Execute via `asyncio.create_subprocess_shell(command, stdout=PIPE, stderr=PIPE, cwd=cwd, env=env)`
8. If `background=True`: register in `BackgroundTaskRegistry`, spawn reader coroutines, return task_id
9. If foreground: `await process.communicate()` with `asyncio.wait_for(timeout)`
10. Return ExecSuccessResponse with stdout/stderr/exit_code/duration_ms

#### `tools/async_wait.py`

Core logic:
1. If `task_id` provided: look up in `BackgroundTaskRegistry`
   - Found: `await task.completion_event.wait()` with `asyncio.wait_for(seconds)`
   - Return early with task result if task completes before timeout
   - Not found: return ErrorResponse(TASK_NOT_FOUND)
2. If no `task_id`: simple `await asyncio.sleep(seconds)`
3. Return WaitResponse with actual waited time and reason

#### `tools/async_search.py`

Core logic:
1. Validate `search.enabled`
2. Compile regex pattern (return INVALID_PATTERN on `re.error`)
3. Resolve search path relative to `_active_project_root`
4. Walk files using `pathlib.Path.rglob(glob_pattern)` or `.glob()`
5. For each file: validate against PathValidator (access rules), check size limit
6. Read file, scan lines with regex, collect matches up to `max_results`
7. Respect ContentScanner rules (skip files with denied content)
8. Return SearchResponse with matches grouped by output_mode

### 3.7 Server Registration (`server.py`)

Add to imports:
```python
from async_crud_mcp.core.shell_validator import ShellValidator
from async_crud_mcp.core.background_tasks import BackgroundTaskRegistry
from async_crud_mcp.models import ExecRequest, WaitRequest, SearchRequest
from async_crud_mcp.tools import async_exec, async_wait, async_search
```

Module-level initialization:
```python
shell_validator = ShellValidator(settings.shell.deny_patterns)
background_tasks = BackgroundTaskRegistry()
```

New tool wrappers (following existing pattern):
```python
@mcp.tool()
async def async_exec_tool(command: str, timeout: float = 120.0, cwd: str | None = None, env: dict[str, str] | None = None, background: bool = False):
    """Execute a shell command with policy enforcement. ..."""
    request = ExecRequest(command=command, timeout=timeout, cwd=cwd, env=env, background=background)
    response = await async_exec(request, shell_validator, background_tasks, _active_project_root, settings.shell)
    return response.model_dump()

@mcp.tool()
async def async_wait_tool(seconds: float = 120.0, task_id: str | None = None):
    """Wait for duration or background task completion. ..."""
    request = WaitRequest(seconds=seconds, task_id=task_id)
    response = await async_wait(request, background_tasks)
    return response.model_dump()

@mcp.tool()
async def async_search_tool(pattern: str, path: str | None = None, glob: str = "*", recursive: bool = True, case_insensitive: bool = False, max_results: int = 100, context_lines: int = 0, output_mode: str = "files_with_matches"):
    """Search file contents using regex patterns. ..."""
    request = SearchRequest(pattern=pattern, path=path, glob=glob, recursive=recursive, case_insensitive=case_insensitive, max_results=max_results, context_lines=context_lines, output_mode=output_mode)
    response = await async_search(request, path_validator, content_scanner, _active_project_root, settings.search)
    return response.model_dump()
```

**Activation requirement**: All 3 new tools require project activation (do NOT add to `_ACTIVATION_EXEMPT_TOOLS`).

### 3.8 Config Hot-Reload Integration

The existing `ConfigWatcher` in `daemon/config_watcher.py` watches `.async-crud-mcp/config.json`. When a reload triggers `_apply_project_config()` in server.py, add:

```python
# Inside _apply_project_config() callback
if project_config.shell_enabled is not None:
    shell_enabled = project_config.shell_enabled
else:
    shell_enabled = settings.shell.enabled

# Merge deny patterns per mode
if project_config.shell_deny_patterns_mode == "extend":
    merged = settings.shell.deny_patterns + project_config.shell_deny_patterns
elif project_config.shell_deny_patterns_mode == "replace":
    merged = project_config.shell_deny_patterns
elif project_config.shell_deny_patterns_mode == "disable":
    merged = []
else:
    merged = settings.shell.deny_patterns

shell_validator.reload(merged)
```

---

## 4. Denylist Strategy

### 4.1 Rationale

**Denylist over allowlist**: An allowlist would break every time a subagent needs a new program. Denylists have known weaknesses but are correct for flexibility.

### 4.2 Coverage Analysis

| Category | Commands Blocked | Coverage |
|----------|-----------------|----------|
| File read | cat, head, tail, less, more | ~95% of read bypasses |
| File write | tee, sed, awk, echo >, printf > | ~90% of write bypasses |
| File ops | cp, mv, rm, dd, touch, mkdir | ~99% of file operation bypasses |
| Search | grep, rg, find, ls | ~99% of search bypasses |
| Anti-circumvention | python -c...open(, node -e...fs. | ~80% of language-level bypasses |

### 4.3 Known Circumvention Vectors

| Vector | Example | Risk | Default Coverage |
|--------|---------|------|-----------------|
| `python -c` file I/O | `python -c "open('f','w').write('x')"` | Medium | YES (default pattern) |
| `node -e` file I/O | `node -e "fs.writeFileSync('f','x')"` | Medium | YES (default pattern) |
| `curl file://` | `curl file:///etc/passwd` | Low | NO (add if needed) |
| `wget -O` | `wget -O output.txt url` | Low | NO (add if needed) |
| `bash -c` | `bash -c 'cat > file <<EOF ...'` | Medium | NO (consider adding) |
| Process substitution | `>(cat > file)` | Very Low | NO |
| `/dev/tcp` | `echo > /dev/tcp/host/port` | Very Low | NO |

### 4.4 Why This Is Acceptable

1. **LLM is not adversarial** - falls back to Bash from training habit, not malice
2. **Deny response redirects** - includes "Use async_read_tool instead" guidance
3. **Hot-reloadable** - add new patterns to config without restart when bypasses discovered
4. **80/20 rule** - default list covers ~90% of bypass attempts

---

## 5. Implementation Order

### Phase 1: Foundation (no external integration)

| Step | File | Action | Depends On |
|------|------|--------|-----------|
| 1.1 | `config.py` | Add ShellDenyPattern, ShellConfig, SearchConfig, extend Settings + ProjectConfig | - |
| 1.2 | `core/shell_validator.py` | NEW: ShellValidator class | 1.1 |
| 1.3 | `core/background_tasks.py` | NEW: BackgroundTaskRegistry class | - |
| 1.4 | `models/requests.py` | Add ExecRequest, WaitRequest, SearchRequest | 1.1 |
| 1.5 | `models/responses.py` | Add 6 new response models + 6 new ErrorCode values | - |
| 1.6 | `models/__init__.py` | Export new models | 1.4, 1.5 |
| 1.7 | `tools/async_exec.py` | NEW: async_exec implementation | 1.2, 1.3, 1.4, 1.5 |
| 1.8 | `tools/async_wait.py` | NEW: async_wait implementation | 1.3, 1.4, 1.5 |
| 1.9 | `tools/async_search.py` | NEW: async_search implementation | 1.4, 1.5 |
| 1.10 | `tools/__init__.py` | Export new tools | 1.7, 1.8, 1.9 |
| 1.11 | `server.py` | Register 3 new tools, init ShellValidator + BackgroundTaskRegistry | 1.7, 1.8, 1.9 |
| 1.12 | `server.py` | Integrate shell config into _apply_project_config hot-reload | 1.11 |

### Phase 2: Tests

| Step | File | Coverage |
|------|------|----------|
| 2.1 | `tests/test_config.py` | ShellConfig, SearchConfig defaults and validation |
| 2.2 | `tests/test_shell_validator.py` | NEW: pattern matching, reload, edge cases |
| 2.3 | `tests/test_tools/test_async_exec.py` | NEW: deny, allow, timeout, background, env strip |
| 2.4 | `tests/test_tools/test_async_wait.py` | NEW: sleep, task wait, early return, timeout |
| 2.5 | `tests/test_tools/test_async_search.py` | NEW: regex, glob, output modes, access control |
| 2.6 | `tests/test_background_tasks.py` | NEW: registry, wait, cleanup |

### Phase 3: Hardening (post-integration)

| Step | Description |
|------|-------------|
| 3.1 | Background task cleanup (TTL, max concurrent tasks) |
| 3.2 | Audit logging for all exec commands (security trail) |
| 3.3 | Rate limiting (prevent runaway command execution) |
| 3.4 | Load testing with concurrent subagents |

---

## 6. Files to Create/Modify

| File | Action | Lines (est.) |
|------|--------|-------------|
| `src/async_crud_mcp/config.py` | MODIFY: +ShellDenyPattern, +ShellConfig, +SearchConfig, extend Settings + ProjectConfig | +80 |
| `src/async_crud_mcp/core/__init__.py` | MODIFY: export ShellValidator, BackgroundTaskRegistry | +2 |
| `src/async_crud_mcp/core/shell_validator.py` | NEW | ~50 |
| `src/async_crud_mcp/core/background_tasks.py` | NEW | ~100 |
| `src/async_crud_mcp/models/requests.py` | MODIFY: +ExecRequest, +WaitRequest, +SearchRequest | +40 |
| `src/async_crud_mcp/models/responses.py` | MODIFY: +6 response models, +6 ErrorCode values | +100 |
| `src/async_crud_mcp/models/__init__.py` | MODIFY: export new models | +10 |
| `src/async_crud_mcp/tools/async_exec.py` | NEW | ~150 |
| `src/async_crud_mcp/tools/async_wait.py` | NEW | ~60 |
| `src/async_crud_mcp/tools/async_search.py` | NEW | ~120 |
| `src/async_crud_mcp/tools/__init__.py` | MODIFY: export new tools | +3 |
| `src/async_crud_mcp/server.py` | MODIFY: +3 tool wrappers, +imports, +init, +hot-reload | +60 |
| `tests/test_config.py` | MODIFY: +ShellConfig/SearchConfig tests | +40 |
| `tests/test_shell_validator.py` | NEW | ~80 |
| `tests/test_tools/test_async_exec.py` | NEW | ~200 |
| `tests/test_tools/test_async_wait.py` | NEW | ~100 |
| `tests/test_tools/test_async_search.py` | NEW | ~150 |
| `tests/test_background_tasks.py` | NEW | ~80 |

**Total**: ~1,425 lines new/modified across 18 files

---

## 7. Verification Checklist

### Denylist Enforcement
- [ ] `async_exec_tool("cat /etc/passwd")` -> ExecDeniedResponse with "Use async_read_tool instead"
- [ ] `async_exec_tool("head -n 10 file.txt")` -> ExecDeniedResponse
- [ ] `async_exec_tool("echo 'test' > file.txt")` -> ExecDeniedResponse
- [ ] `async_exec_tool("python -c \"open('f','w').write('x')\"")` -> ExecDeniedResponse
- [ ] `async_exec_tool("grep pattern *.py")` -> ExecDeniedResponse
- [ ] `async_exec_tool("ls /tmp")` -> ExecDeniedResponse

### Legitimate Execution
- [ ] `async_exec_tool("python -m pytest tests/")` -> ExecSuccessResponse with stdout
- [ ] `async_exec_tool("git status")` -> ExecSuccessResponse
- [ ] `async_exec_tool("npm run build")` -> ExecSuccessResponse
- [ ] `async_exec_tool("ruff check src/")` -> ExecSuccessResponse (ruff != rg)

### Background Mode
- [ ] `async_exec_tool("sleep 10", background=True)` -> ExecBackgroundResponse with task_id
- [ ] `async_wait_tool(task_id="...")` -> WaitResponse with task result

### Wait Tool
- [ ] `async_wait_tool(seconds=5)` -> WaitResponse after ~5 seconds
- [ ] `async_wait_tool(seconds=300, task_id="...")` -> early return on task completion

### Search Tool
- [ ] `async_search_tool(pattern="def main", glob="*.py")` -> file matches
- [ ] `async_search_tool(pattern="TODO", output_mode="content", context_lines=2)` -> line matches with context
- [ ] `async_search_tool(pattern="...", path="/outside/base")` -> ACCESS_DENIED via PathValidator

### Hot-Reload
- [ ] Update `.async-crud-mcp/config.json` with new deny pattern -> active within `config_debounce_seconds`
- [ ] Set `shell_deny_patterns_mode: "replace"` -> only project patterns active
- [ ] Set `shell_deny_patterns_mode: "disable"` -> all commands allowed

### Conflict Detection (existing)
- [ ] Two subagents update queue.json simultaneously via `async_update_tool` -> one gets ContentionResponse with diff

---

## 8. Dependencies

No new PyPI dependencies required. All implementations use stdlib:
- `asyncio` (subprocess, events, sleep)
- `re` (regex compilation and matching)
- `pathlib` (file walking for search)
- `os` (environment variable handling)
- `time` (timestamps, duration measurement)

---

## 9. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Denylist false positives (blocking legitimate commands) | Medium | Hot-reloadable config, per-project overrides |
| Background task leaks (orphaned processes) | Medium | TTL-based cleanup in Phase 3 |
| Regex catastrophic backtracking | Low | Compile-time validation, timeout on pattern matching |
| Large search results consuming memory | Low | max_results cap, streaming not needed at MCP scale |
| env_strip missing new nesting guards | Low | Document and update as Claude Code evolves |

---

## 10. References

- Plan file: `~/.claude/plans/curious-yawning-minsky.md`
- async-crud-mcp source: `C:\Users\Admin\Documents\GitHub\async-crud-mcp\src\async_crud_mcp\`
- Existing patterns: `server.py` tool registration, `models/` request/response structure
- Config architecture: `config.py` Pydantic settings with hot-reload
- Integration plan: See `claude-code-tooling/claude-commands/.claude/implementation/shell-integration-plan.md`
