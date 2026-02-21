# Plan: Path-Based Access Control for Destructive Operations (Revised)

## Context

Investigated the async-crud-mcp MCP server configuration infrastructure to answer specific feedback on CLIENT-SIDE configuration mechanisms for the proposed path-based access control system. The key question is: how does a caller configure access rules without baking them into the server? Research covered the full config loading chain from `claude_desktop_config.json` through `Settings`, plus the FastMCP lifecycle API.

---

## Findings

### Configuration Loading Chain

**server.py:60** calls `get_settings()` with NO arguments. This delegates to the module-level singleton in `config.py:177-210` which reads from:
1. Environment variables (`ASYNC_CRUD_MCP_<SECTION>__<FIELD>` prefix, via pydantic-settings)
2. The platform-global config file at `get_config_file_path()` (e.g., `%LOCALAPPDATA%\async-crud-mcp\config\config.json` on Windows)
3. Pydantic defaults

Critically, **there is no `--config` CLI argument** to `server.py`. The server process launched by `bootstrap_daemon.py:296-297` uses `[python_exe, "-m", "async_crud_mcp.server"]` with no additional args. The config file path is fixed by platform convention; there is no mechanism to pass an alternate config path at launch.

**Three viable channels** exist for injecting access rules from the client side:

1. **Environment variables** (highest priority in pydantic-settings): Client config (`claude_desktop_config.json`) can set env vars in the `"env"` block of the `mcpServers` entry. These take precedence over the config file.

2. **Platform config file** (`config.json`): The server always reads from the platform-standard path. Rules added here affect all sessions for that user. This is a global-but-per-user scope -- one config per OS user, not per project.

3. **Runtime `configure_access_policy` MCP tool**: A new tool that the client calls after connecting, dynamically replacing or extending the active policy for the current server session. This enables project-scoped rules passed at runtime.

### FastMCP Lifecycle Hooks

`FastMCP` supports a **`lifespan`** parameter (server.py:166 in fastmcp): a context manager called once at server startup. The `Context` object (context.py) is per-request and carries `RequestContext` from the MCP protocol but does NOT receive custom client-provided initialization data (no equivalent of HTTP headers or gRPC metadata). There is no MCP-level mechanism for the client to pass structured initialization parameters at connection time beyond what the protocol defines (capabilities only).

**Conclusion**: MCP protocol does not provide a built-in "client sends config to server at init" mechanism. The practical options are env vars (static, set in `claude_desktop_config.json`) or a runtime tool call.

### Per-Project Config File via Env Var

The most elegant project-scoped solution: add a `ASYNC_CRUD_MCP_CONFIG_FILE` env var that `get_settings()` checks to load an alternate config file, overriding the platform-global path. The client sets this in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "async-crud-mcp": {
      "command": "python",
      "args": ["-m", "async_crud_mcp.server"],
      "env": {
        "ASYNC_CRUD_MCP_CONFIG_FILE": "/path/to/project/.mcp-access-policy.json"
      },
      "transport": { "type": "sse", "url": "http://127.0.0.1:8720/sse" }
    }
  }
}
```

This provides project-scoped rules without changing the server launch command. The config file at the project path contains `crud.access_rules`.

### Config Schema After Implementation

**`CrudConfig` extension** in `config.py:68-76`:

```json
{
  "crud": {
    "base_directories": ["/project/root"],
    "_comment": "access_rules: first-match wins, ordered by priority desc",
    "access_rules": [
      {
        "path": "/project/root/.claude/sprint/subagent-output",
        "operations": ["write", "append"],
        "action": "allow",
        "priority": 100
      },
      {
        "path": "/project/root/src",
        "operations": ["write", "update", "delete", "rename", "append"],
        "action": "deny",
        "priority": 50
      },
      {
        "path": "/project/root/.claude",
        "operations": ["write", "update", "delete", "rename", "append"],
        "action": "deny",
        "priority": 50
      }
    ],
    "default_destructive_policy": "deny"
  }
}
```

**Per-persona config examples**:

*Planning subagent* (read-only -- all destructive ops denied by default policy, no rules needed):
```json
{ "crud": { "base_directories": ["/project"], "default_destructive_policy": "deny" } }
```

*Implementation subagent* (writes to subagent-output only):
```json
{
  "crud": {
    "base_directories": ["/project"],
    "access_rules": [
      { "path": "/project/.claude/sprint/subagent-output", "operations": ["write", "append"], "action": "allow", "priority": 100 }
    ],
    "default_destructive_policy": "deny"
  }
}
```

*Full-access subagent* (unrestricted within project):
```json
{ "crud": { "base_directories": ["/project"], "default_destructive_policy": "allow" } }
```

### Rule Evaluation Design

- **First-match wins** (ordered by `priority` descending, then list order as tiebreaker)
- `operations: ["*"]` is shorthand for all destructive operations
- Path matching: prefix match (same logic as existing `PathValidator.validate()` at `path_validator.py:104-117`)
- Read operations (`async_read`, `async_batch_read`, `async_list`, `async_status`) are **never** subject to access rules -- they remain controlled only by `base_directories`
- If no rule matches, `default_destructive_policy` applies (defaults to `"allow"` for backward compat)

### Runtime Tool Option (Optional Enhancement)

A `configure_access_policy_tool` MCP tool that accepts `access_rules` and `default_destructive_policy` as JSON args, replacing the live policy object on the `path_validator` instance. This supports dynamic per-session policy without requiring a new config file per project. The trade-off is that it requires an explicit tool call after connection (orchestrator must call it before delegating to the subagent). This is useful when the client cannot easily control the `env` block (e.g., stdio transport with fixed launch args).

---

## Recommendations

**Recommended implementation order**:

1. **Add `PathRule` model and extend `CrudConfig`** in `config.py:68-76` -- pure data model change, no behavioral impact yet.

2. **Add `ASYNC_CRUD_MCP_CONFIG_FILE` env var support** in `config.py:177-210` (`get_settings()`) -- enables project-scoped config files without touching the server launch mechanism.

3. **Extend `PathValidator` with `validate_operation(path, op_type)`** in `path_validator.py:56` -- new method that checks access rules after base-directory validation succeeds.

4. **Update all 7 destructive tool functions** to call `validate_operation()` instead of `validate()`.

5. **Optional**: Add `configure_access_policy_tool` to `server.py` as a runtime configuration mechanism.

**Key trade-offs**:
- Env var + per-project config file is the cleanest solution; no server changes needed to the launch mechanism.
- The `default_destructive_policy` default **must be `"allow"`** to preserve backward compatibility for users without `access_rules` configured.
- For the sprint subagent use case, project `.mcp-access-policy.json` files committed to the repo are the right long-term pattern; env var injection from `claude_desktop_config.json` or `plan-settings.json` is the short-term bridge.

---

## Files Identified

| File | Lines | Relevance |
|------|-------|-----------|
| `src/async_crud_mcp/config.py` | L68-76 | Add `PathRule` Pydantic model; extend `CrudConfig` with `access_rules: list[PathRule]` and `default_destructive_policy` |
| `src/async_crud_mcp/config.py` | L177-210 | Extend `get_settings()` to check `ASYNC_CRUD_MCP_CONFIG_FILE` env var for project-scoped config override |
| `src/async_crud_mcp/core/path_validator.py` | L56-123 | Add `validate_operation(path, op_type)` method; store `access_rules` and `default_destructive_policy` in `__init__` |
| `src/async_crud_mcp/core/__init__.py` | L1-27 | Export `PathRule` and `AccessDeniedError` (new) if added as separate exception |
| `src/async_crud_mcp/server.py` | L61 | Pass `access_rules` and `default_destructive_policy` to `PathValidator` constructor |
| `src/async_crud_mcp/tools/async_write.py` | L39-46 | Change `path_validator.validate()` -> `path_validator.validate_operation(request.path, "write")` |
| `src/async_crud_mcp/tools/async_update.py` | (same pattern) | Change to `validate_operation(path, "update")` |
| `src/async_crud_mcp/tools/async_delete.py` | (same pattern) | Change to `validate_operation(path, "delete")` |
| `src/async_crud_mcp/tools/async_append.py` | (same pattern) | Change to `validate_operation(path, "append")` (maps to "write" op type) |
| `src/async_crud_mcp/tools/async_rename.py` | (same pattern) | Validate `old_path` as "delete", `new_path` as "write" |
| `src/async_crud_mcp/tools/async_batch_write.py` | per-item loop | Per-item `validate_operation()` calls |
| `src/async_crud_mcp/tools/async_batch_update.py` | per-item loop | Per-item `validate_operation()` calls |
| `src/async_crud_mcp/models/responses.py` | L16 | Use existing `ACCESS_DENIED` error code for policy denials (distinct from `PATH_OUTSIDE_BASE`) |
| `src/async_crud_mcp/daemon/config_init.py` | L285-323 | Update `generate_default_config()` to include empty `access_rules` in default config template |
| `tests/test_path_validator.py` | L1-60+ | Add tests for `validate_operation()`, rule priority, default policy, and env var config override |
