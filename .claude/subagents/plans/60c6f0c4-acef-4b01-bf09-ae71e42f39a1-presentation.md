# Plan: Path-Based Access Control for Destructive Operations

## Context

**Problem**: The async-crud-mcp server currently lacks fine-grained access control for destructive operations (write, delete, update, rename). Project subagents need to be restricted to specific directories while the sprint framework requires role-based policy configuration without server restart.

**Solution**: Implement a configuration-driven access control system using Pydantic models with project-scoped rules injected via environment variables. Rules are evaluated first-match-wins against destructive operations, while read operations remain unrestricted. The system supports per-project `.mcp-access-policy.json` files referenced from `claude_desktop_config.json`.

## Changes

### Configuration System

#### File: `src/async_crud_mcp/config.py` (L68-76 + L177-210)

**Currently**:
- `CrudConfig` exists but lacks access control fields
- `get_settings()` reads platform-global config only via `get_config_file_path()`

**Changes**:
1. **Add `PathRule` Pydantic model** (L68-76):
   - Fields: `path` (str), `operations` (list[str]), `action` ("allow"|"deny"), `priority` (int)
   - Allows `operations: ["*"]` as shorthand for all destructive ops

2. **Extend `CrudConfig`** (L68-76):
   - Add `access_rules: list[PathRule] = []`
   - Add `default_destructive_policy: str = "allow"` (preserves backward compat)

3. **Add env var override** (L177-210):
   - Check `ASYNC_CRUD_MCP_CONFIG_FILE` environment variable in `get_settings()`
   - Load project-scoped config from this path if set, taking precedence over platform-global config
   - Enables `claude_desktop_config.json` to inject: `"env": {"ASYNC_CRUD_MCP_CONFIG_FILE": "/path/to/.mcp-access-policy.json"}`

### Path Validator Enhancement

#### File: `src/async_crud_mcp/core/path_validator.py` (L56-123)

**Currently**:
- `__init__` stores `base_directories` and validates paths against them
- `validate(path)` checks only base-directory membership

**Changes**:
1. **Add rule storage in `__init__`**:
   - Accept `access_rules` and `default_destructive_policy` parameters from config
   - Store as instance attributes

2. **Add `validate_operation(path, op_type)` method**:
   - First calls existing `validate()` to check base-directory membership
   - Then evaluates `access_rules` in priority-descending order (first match wins)
   - Returns allow/deny decision based on rule action or default policy
   - Read operations (`async_read`, `async_batch_read`, `async_list`, `async_status`) bypass this check entirely

### Server Initialization

#### File: `src/async_crud_mcp/server.py` (L61)

**Currently**: Constructs `PathValidator` with only `base_directories` from config

**Changes**:
- Pass `access_rules` and `default_destructive_policy` from settings to `PathValidator` constructor

### Destructive Tool Updates

#### Files: `async_write.py`, `async_update.py`, `async_delete.py`, `async_append.py`, `async_rename.py`, `async_batch_write.py`, `async_batch_update.py` (L39-46 + per-item loops)

**Currently**: Each destructive tool calls `path_validator.validate(path)` for base-directory checking only

**Changes**:
- Replace `path_validator.validate(path)` with `path_validator.validate_operation(path, op_type)`
- Operation type mapping:
  - `async_write` → `"write"`
  - `async_update` → `"update"`
  - `async_delete` → `"delete"`
  - `async_append` → `"write"` (write variant)
  - `async_rename` → `"delete"` for `old_path`, `"write"` for `new_path`
  - Batch tools → per-item calls in loops

### Response Codes

#### File: `src/async_crud_mcp/models/responses.py` (L16)

**Currently**: Uses `PATH_OUTSIDE_BASE` error code for base-directory violations

**Changes**:
- Use existing `ACCESS_DENIED` error code for policy-based denials (distinct from `PATH_OUTSIDE_BASE`)
- Allows clients to distinguish between "path not in base directories" vs. "operation denied by access rule"

### Configuration Template

#### File: `src/async_crud_mcp/daemon/config_init.py` (L285-323)

**Currently**: Default config template omits access control fields

**Changes**:
- Update `generate_default_config()` to include empty `access_rules: []` in template
- Ensures new installations have the schema available

### Exports

#### File: `src/async_crud_mcp/core/__init__.py` (L1-27)

**Changes**:
- Export `PathRule` model for public API
- Export `AccessDeniedError` exception if created as separate exception class (optional)

## Files to Modify

| File | Change |
|------|--------|
| `src/async_crud_mcp/config.py` | Add `PathRule` model; extend `CrudConfig` with `access_rules` and `default_destructive_policy`; add `ASYNC_CRUD_MCP_CONFIG_FILE` env var support to `get_settings()` |
| `src/async_crud_mcp/core/path_validator.py` | Add `validate_operation(path, op_type)` method; store rules and default policy |
| `src/async_crud_mcp/server.py` | Pass config rules to `PathValidator` constructor |
| `src/async_crud_mcp/tools/async_write.py` | Use `validate_operation(path, "write")` |
| `src/async_crud_mcp/tools/async_update.py` | Use `validate_operation(path, "update")` |
| `src/async_crud_mcp/tools/async_delete.py` | Use `validate_operation(path, "delete")` |
| `src/async_crud_mcp/tools/async_append.py` | Use `validate_operation(path, "write")` |
| `src/async_crud_mcp/tools/async_rename.py` | Validate `old_path` as "delete", `new_path` as "write" |
| `src/async_crud_mcp/tools/async_batch_write.py` | Per-item `validate_operation()` calls |
| `src/async_crud_mcp/tools/async_batch_update.py` | Per-item `validate_operation()` calls |
| `src/async_crud_mcp/models/responses.py` | Use `ACCESS_DENIED` for policy violations |
| `src/async_crud_mcp/daemon/config_init.py` | Add empty `access_rules` to default config template |
| `src/async_crud_mcp/core/__init__.py` | Export `PathRule` |
| `tests/test_path_validator.py` | Add tests for rule evaluation, priority ordering, default policy, env var override |

## Verification

1. Create a test `.mcp-access-policy.json` with `access_rules` array containing allow/deny rules at different priorities
2. Verify `validate_operation()` returns correct decision for paths matching multiple rules (first-match wins by priority desc)
3. Verify `validate_operation()` respects `default_destructive_policy` when no rules match
4. Set `ASYNC_CRUD_MCP_CONFIG_FILE` env var and confirm server loads project config instead of platform-global config
5. Call a destructive tool with a denied path and verify `ACCESS_DENIED` error response (not `PATH_OUTSIDE_BASE`)
6. Call a read operation with any path and confirm it bypasses access rule checks (base-directory only)
7. Test backward compatibility: server with no `access_rules` configured should behave as before (default policy = "allow")

## Key Design Decisions

- **First-match-wins rule evaluation** (priority descending): Simplifies policy expression and avoids ambiguous multi-match scenarios
- **Env var override for project scope**: Avoids server restart and allows `claude_desktop_config.json` to control policy per project
- **Default policy = "allow"**: Ensures backward compatibility for existing deployments without `access_rules` configured
- **Read operations exempted**: Access rules apply to destructive operations only; read operations remain controlled by `base_directories` alone
- **`ACCESS_DENIED` distinct from `PATH_OUTSIDE_BASE`**: Allows clients to distinguish policy violations from boundary violations
