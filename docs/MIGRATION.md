# Migration Guide: Native Tools to async-crud-mcp

This guide helps AI agents and developers migrate from Claude Code's native file operation tools (Read, Write, Edit, Glob, Grep, Bash) to the async-crud-mcp equivalents.

## Why Migrate

async-crud-mcp provides file-locking CRUD operations that prevent concurrent agents from silently overwriting each other's work. When an update conflicts, the server returns a diff-based contention response instead of a bare error, saving a full file re-read.

## Tool Mapping

| Native Tool | async-crud-mcp Tool | Notes |
|-------------|---------------------|-------|
| `Read(file_path)` | `async_read_tool(path)` | Supports `offset`/`limit` for pagination, `encoding` |
| `Write(file_path, content)` | `async_write_tool(path, content)` | Atomic writes, 256 MB limit, `create_dirs` option |
| `Edit(file_path, old_string, new_string)` | `async_update_tool(path, expected_hash, patches=[...])` | Hash-based conflict detection; see [Update Modes](#update-modes) |
| `Glob(pattern)` | `async_list_tool(path, pattern, recursive)` | Uses `fnmatch`; see [Glob Differences](#glob-pattern-differences) |
| `Grep(pattern)` | `async_search_tool(pattern, path, glob)` | Regex search with context lines; see [Search Differences](#search-differences) |
| `Bash(command)` | `async_exec_tool(command)` | Deny-pattern enforcement; see [Shell Restrictions](SHELL_RESTRICTIONS.md) |
| `cat`, `head`, `tail` | `async_read_tool(path, offset, limit)` | Blocked in exec; use read tool instead |
| `cp` | `async_read_tool` + `async_write_tool` | Blocked in exec; read source, write destination |
| `mv` | `async_rename_tool(path, new_path)` | Blocked in exec; use rename tool |
| `rm` | `async_delete_tool(path)` | Blocked in exec; moves to recycle bin by default |

## Update Modes

`async_update_tool` supports three mutually exclusive update strategies:

### 1. Full Content Replacement

Replace the entire file:

```json
{
  "path": "src/app.py",
  "expected_hash": "sha256:abc123...",
  "content": "# Full new file content\nprint('hello')\n"
}
```

### 2. Exact-Match Patches

Replace specific strings (equivalent to the native Edit tool):

```json
{
  "path": "src/app.py",
  "expected_hash": "sha256:abc123...",
  "patches": [
    {"old_string": "def old_name()", "new_string": "def new_name()"}
  ]
}
```

### 3. Regex Patches

Pattern-based replacements for flexible edits:

```json
{
  "path": "src/app.py",
  "expected_hash": "sha256:abc123...",
  "regex_patches": [
    {"pattern": "v\\d+\\.\\d+\\.\\d+", "replacement": "v2.0.0", "count": 0}
  ]
}
```

- `pattern`: Python regex pattern
- `replacement`: Replacement string (supports `\1`, `\g<name>` backreferences)
- `count`: Max replacements (0 = unlimited)

Regex patches include a content scanner guard: matches containing sensitive patterns (API keys, tokens, private keys) are blocked and reported in the `regex_blocked` response array.

## Conflict Detection

All update operations require `expected_hash` (obtained from a prior read or write response). If the file changed since your last read:

- The server returns a `ContentionResponse` with:
  - `diff`: What changed (JSON or unified format)
  - `current_hash`: The hash you need for your retry
  - `modified_by`: `"agent"` (another CRUD user), `"external"` (edited outside CRUD), or `"unknown"`

This avoids re-reading the entire file just to retry an update.

## Glob Pattern Differences

### Native Glob Tool

The native `Glob` tool supports full glob syntax including:
- `*` - match any characters within a path segment
- `**` - match zero or more path segments (recursive descent)
- `?` - match a single character
- `[abc]` - character classes
- `{a,b}` - brace expansion

Example: `**/*.py` matches all Python files in all subdirectories.

### async_list_tool

`async_list_tool` uses Python's `fnmatch` module, which matches against **individual file/directory names**, not full paths.

**Key differences:**

| Pattern | Native Glob | async_list_tool |
|---------|------------|-----------------|
| `**/*.py` | All `.py` files recursively | Not supported |
| `*.py` | `.py` files in current dir | `.py` files (use `recursive: true` for subdirs) |
| `test_*` | Files starting with `test_` | Same behavior |
| `*.{js,ts}` | JS and TS files | Not supported (no brace expansion) |

**How to achieve the same results:**

| Goal | Native Glob | async_list_tool Equivalent |
|------|------------|---------------------------|
| All `.py` files recursively | `Glob("**/*.py")` | `async_list_tool(path, pattern="*.py", recursive=true)` |
| All files in one dir | `Glob("src/*")` | `async_list_tool(path="src")` |
| Specific extension, one dir | `Glob("src/*.ts")` | `async_list_tool(path="src", pattern="*.ts")` |
| Multiple extensions | `Glob("**/*.{js,ts}")` | Two calls: `pattern="*.js"` and `pattern="*.ts"` |

### Workaround for Complex Patterns

For patterns that `fnmatch` cannot express, use `async_search_tool` with a broad file glob and filter results by path regex, or make multiple `async_list_tool` calls with simple patterns.

## Search Differences

### Native Grep Tool

The native `Grep` tool uses ripgrep (`rg`) under the hood with features like:
- `type` parameter for file type filtering (e.g., `"py"`, `"js"`)
- `-A`, `-B`, `-C` context line parameters
- `files_with_matches`, `content`, and `count` output modes
- High performance on large repos (Rust-based)

### async_search_tool

`async_search_tool` uses Python's `re` module for regex matching with a linear file scan:

| Feature | Native Grep | async_search_tool |
|---------|------------|-------------------|
| Regex engine | ripgrep (Rust) | Python `re` |
| File type filter | `type: "py"` | `glob: "*.py"` |
| Context lines | `-A`/`-B`/`-C` (separate) | `context_lines` (symmetric only) |
| Output modes | `content`, `files_with_matches`, `count` | Same three modes |
| Max results | Via `head_limit` | `max_results` (default: 100) |
| Case insensitive | `-i: true` | `case_insensitive: true` |
| Performance | Optimized for large repos | Linear scan; slower on 10k+ files |
| Content scanning | N/A | Matches in sensitive files may be redacted |

**Parameter mapping:**

```
Grep(pattern="TODO", type="py", output_mode="content", -C=2)
   =>
async_search_tool(pattern="TODO", glob="*.py", output_mode="content", context_lines=2)
```

## Batch Operations

async-crud-mcp supports batch versions of read, write, and update for multi-file operations in a single call:

- `async_batch_read_tool(files=[{"path": "a.py"}, {"path": "b.py"}])`
- `async_batch_write_tool(files=[{"path": "a.py", "content": "..."}, ...])`
- `async_batch_update_tool(files=[{"path": "a.py", "expected_hash": "...", "patches": [...]}])`

These are more efficient than sequential single-file calls when operating on multiple files.

## Project Activation

Before using any CRUD tool, the project must be activated:

```
crud_activate_project(project_root="/path/to/project")
```

This sets the base directory for path validation. All file operations are restricted to paths within the activated project root. Activation is required once per session.

## Recycle Bin

`async_delete_tool` moves files to a recycle bin instead of permanent deletion. Use:

- `async_restore_tool(recycle_name)` - Restore a deleted file
- `async_recycle_list_tool(limit)` - List recycled files
- `async_recycle_clean_tool(retention_days)` - Purge old entries

Recycle entries are signed with HMAC-SHA256 to prevent metadata tampering.
