# Plan: Path-Based Access Control for Destructive Operations

## Context

**Problem**: Subagents launched via Claude Code CLI need fine-grained access control over file operations. Currently, destructive tools (write, delete, update, append, rename) validate only that paths are within base directories, with no policy-based restrictions. This creates security risks when orchestrating subagents that should only modify specific project directories (e.g., `.claude/subagents/plans` for planners, `src/` for implementation agents).

**Solution**: Implement a hierarchical access control system using JSON policy files, environment variable propagation through Claude Code CLI settings, and a new `validate_operation()` method in `PathValidator` that enforces rules based on path prefix matching with priority ordering. The policy file is loaded once at session startup and is immutable for the session lifetime.

## Changes

### File: `src/async_crud_mcp/config.py` (68-210)

**Currently**: `CrudConfig` contains only `base_directories`. `get_settings()` loads and caches the settings object.

**Changes**:
- **L68 (before CrudConfig)**: Add new `PathRule` Pydantic model with fields:
  - `path: str` - path pattern for matching
  - `operations: list[str]` - operations this rule applies to ("read", "write", "delete", "update", "append", or "*")
  - `action: Literal["allow","deny"]` - allow or deny access
  - `priority: int = 0` - numeric priority (higher wins)

- **L68-76 (CrudConfig)**: Add three new fields:
  - `access_rules: list[PathRule] = Field(default_factory=list)` - rules to enforce
  - `access_policy_file: str | None = None` - path to external policy JSON
  - `default_destructive_policy: Literal["allow","deny"] = "allow"` - fallback when no rule matches

- **L177-210 (get_settings)**: After `Settings()` is constructed, check if `settings.crud.access_policy_file` is set. If yes, resolve the path relative to `os.getcwd()`, load the JSON file, merge its `access_rules` and `default_destructive_policy` into the settings object before caching.

### File: `src/async_crud_mcp/core/path_validator.py` (38-123+)

**Currently**: `PathValidator` validates only base directory containment via `validate()` method.

**Changes**:
- **L13-15 (after imports)**: Add new exception subclass `AccessDeniedError(PathValidationError)` to distinguish policy denials from base directory violations.

- **L38-54 (__init__)**: Add two new parameters:
  - `access_rules: list | None = None` - list of PathRule objects
  - `default_destructive_policy: str = "allow"` - default policy fallback
  - Pre-sort `access_rules` by priority descending at initialization for O(1) first-match lookup.

- **L123+ (new method)**: Add `validate_operation(path: str, op_type: str) -> Path` method:
  - First calls `self.validate(path)` to check base directory containment
  - Then normalizes the path and walks sorted rules in priority order
  - Returns first matching rule's action; on deny, raise `AccessDeniedError`
  - If no rule matches, apply `default_destructive_policy`
  - Returns validated `Path` on allow

### File: `src/async_crud_mcp/core/__init__.py` (L7)

**Currently**: Exports `PathValidator` only.

**Changes**: Add `AccessDeniedError` to the export list to make it available to tool modules.

### File: `src/async_crud_mcp/server.py` (L61)

**Currently**: Instantiates `PathValidator` with only `base_directories` parameter.

**Changes**: Pass two additional parameters:
- `access_rules=settings.crud.access_rules`
- `default_destructive_policy=settings.crud.default_destructive_policy`

### File: `src/async_crud_mcp/tools/async_write.py` (L40-46)

**Currently**: Calls `path_validator.validate(request.path)` at L40.

**Changes**: Replace with `path_validator.validate_operation(request.path, "write")`. In the except block, catch both `PathValidationError` and `AccessDeniedError`, returning `ErrorCode.ACCESS_DENIED` for access denials vs `ErrorCode.PATH_OUTSIDE_BASE` for base directory violations.

### File: `src/async_crud_mcp/tools/async_update.py` (L57-63)

**Currently**: Calls `path_validator.validate(request.path)` at L57.

**Changes**: Replace with `path_validator.validate_operation(request.path, "update")`. Update error handling to distinguish `AccessDeniedError`.

### File: `src/async_crud_mcp/tools/async_delete.py` (L47-53)

**Currently**: Calls `path_validator.validate(request.path)` at L47.

**Changes**: Replace with `path_validator.validate_operation(request.path, "delete")`. Update error handling.

### File: `src/async_crud_mcp/tools/async_append.py` (L44-50)

**Currently**: Calls `path_validator.validate(request.path)` at L44.

**Changes**: Replace with `path_validator.validate_operation(request.path, "write")` (append counts as write permission). Update error handling.

### File: `src/async_crud_mcp/tools/async_rename.py` (L46-55)

**Currently**: Validates both `old_path` and `new_path` in a single try block at L46-49.

**Changes**: Replace with TWO separate calls in SEPARATE try/except blocks:
- `validate_operation(old_path, "delete")` - old path requires delete permission
- `validate_operation(new_path, "write")` - new path requires write permission
- Each should return appropriate error code independently.

### File: `tests/test_path_validator.py` (new test cases)

**Currently**: Contains tests for base directory validation only.

**Changes**: Add test cases for:
- `validate_operation()` allow and deny rule enforcement
- Priority ordering (higher priority rule wins)
- Default policy fallback when no rule matches
- Path prefix matching normalization
- Operation type matching including wildcard `"*"`

## Files to Modify

| File | Change |
|------|--------|
| `src/async_crud_mcp/config.py` | Add `PathRule` model; extend `CrudConfig` with `access_rules`, `access_policy_file`, `default_destructive_policy`; extend `get_settings()` to load policy file |
| `src/async_crud_mcp/core/path_validator.py` | Add `AccessDeniedError` exception; add `access_rules` and `default_destructive_policy` to `__init__()`; add `validate_operation()` method |
| `src/async_crud_mcp/core/__init__.py` | Export `AccessDeniedError` |
| `src/async_crud_mcp/server.py` | Pass access rules to `PathValidator` constructor |
| `src/async_crud_mcp/tools/async_write.py` | Call `validate_operation(path, "write")` instead of `validate(path)` |
| `src/async_crud_mcp/tools/async_update.py` | Call `validate_operation(path, "update")` instead of `validate(path)` |
| `src/async_crud_mcp/tools/async_delete.py` | Call `validate_operation(path, "delete")` instead of `validate(path)` |
| `src/async_crud_mcp/tools/async_append.py` | Call `validate_operation(path, "write")` instead of `validate(path)` |
| `src/async_crud_mcp/tools/async_rename.py` | Two separate `validate_operation()` calls with distinct error handling |
| `src/async_crud_mcp/models/responses.py` | No change (ACCESS_DENIED already exists at L16) |
| `tests/test_path_validator.py` | Add test cases for `validate_operation()` with rules, priority, defaults |

## Key Design Decisions

1. **Hierarchical config with three levels**: Global defaults in `%LOCALAPPDATA%`, project-level policy file committed to repo (`.claude/access-policies/`), and session-level selection via Claude Code CLI `--settings` env block.

2. **Immutable policy per session**: The policy is loaded once at startup before tool registration and cannot be modified at runtime by the agent, ensuring security guarantees for the entire session.

3. **Env var propagation via Claude Code CLI**: Each subagent spawns its own MCP server subprocess with isolated environment, so `ASYNC_CRUD_MCP_CRUD__ACCESS_POLICY_FILE` in the `--settings` file directly reaches the MCP server's `os.environ` before `get_settings()` is called.

4. **Separate exception type for policy denials**: `AccessDeniedError(PathValidationError)` distinguishes policy-driven denials from base directory violations, enabling different error codes in responses.

5. **Dual path validation for rename**: `old_path` is treated as delete (requires delete permission), `new_path` as write (requires write permission), validated independently with separate error returns.

6. **Backward compatibility**: Default policy is `"allow"` with empty rules list, preserving current permissive behavior when no policy is configured.

## Verification

1. Add test policy file `.claude/access-policies/test-planner.json` and verify `get_settings()` loads it and merges rules into `CrudConfig`.
2. Call `validate_operation(path, "write")` with an allow rule and verify it returns the normalized path.
3. Call `validate_operation(path, "write")` with a deny rule and verify it raises `AccessDeniedError`.
4. Test priority ordering: add two rules for same path with different priorities and verify higher priority wins.
5. Test default policy: remove all matching rules and verify `default_destructive_policy` determines access.
6. In async_write, verify that calling `validate_operation()` correctly returns `ErrorCode.ACCESS_DENIED` on denial.
7. In async_rename, verify that `old_path` and `new_path` are validated independently with correct error codes.
8. Create a mock subagent session with Claude Code CLI and verify env var from `--settings` file reaches MCP server's `os.environ`.
