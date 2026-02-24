# Plan: Production Readiness Assessment for async-crud-mcp

## Context

**Problem**: async-crud-mcp aims to replace Claude Code CLI's native file operation tools (Read, Write, Edit, Glob, Grep, Bash) in production. The evaluation identified feature gaps, security vulnerabilities, and performance bottlenecks that need addressing before production deployment.

**Solution**: Implement three critical features (regex-based editing, secure default path validation, external edit detection), harden security (shell command parsing, recycle bin integrity), and add infrastructure for scalability (distributed locks, search indexing). Deprecate unnecessary streaming support (already atomic writes). Non-blocking improvements include documentation of tool limitations.

## Changes

### Feature Completeness

#### Async_read Tool - Pagination ✓ Complete
- **Current**: Already supports `offset` and `limit` parameters with response metadata
- **Status**: No changes required - meets all pagination requirements
- **Reference**: `src/async_crud_mcp/models/requests.py:L22-23`, `src/async_crud_mcp/tools/async_read.py:L95-123`

#### Async_write Tool - Atomic Operation ✓ Complete
- **Current**: Uses atomic write helper with 256MB file size limit enforced
- **Status**: No changes required - 256MB limit confirmed acceptable, no streaming needed
- **Reference**: `src/async_crud_mcp/tools/async_write.py:L66-77`

#### Async_update Tool - Add Regex Editing (CRITICAL)
- **Current**: Only supports full content replacement or exact string match patching
- **Missing**: Regex-based pattern matching for flexible edits
- **Change**: Add `regex_patches` field to `AsyncUpdateRequest` model accepting `RegexPatch(pattern, replacement)` objects
- **Implementation**: Validate regex patterns compile before acquiring lock, apply substitutions with match count tracking in patch loop
- **Files**:
  - `src/async_crud_mcp/models/requests.py:L11-15, L37-59` (add RegexPatch model and regex_patches field)
  - `src/async_crud_mcp/tools/async_update.py:L264-287` (add regex substitution logic)

#### Async_exec Tool - Shell Restrictions
- **Current**: Blocks file operations (cat, head, tail, sed, awk, cp, mv, rm) via deny patterns
- **Status**: By design to force CRUD tool usage. No changes required - this prevents audit trail bypass
- **Reference**: `src/async_crud_mcp/config.py:L224-299`

#### Async_list Tool - Glob Patterns (MEDIUM)
- **Current**: Uses `fnmatch` for pattern matching without `**` recursive syntax support
- **Status**: Documented limitation only - add migration guide for native Glob users
- **Reference**: `src/async_crud_mcp/tools/async_list.py:L69-183`

#### Async_search Tool - Performance (MEDIUM)
- **Current**: Linear O(n × file_size) scan without indexing or parallelization
- **Status**: Slow on large repos (>10k files) - recommend optional trigram indexing on project activation
- **Reference**: `src/async_crud_mcp/tools/async_search.py:L104-145`

### Security Hardening

#### Path Validation - Insecure Empty Config (CRITICAL)
- **Current**: `PathValidator` allows all paths if `base_directories` is empty
- **Issue**: No safe default fallback - creates full filesystem access vulnerability
- **Change**: Default `base_directories` to current working directory if empty, add warning log
- **File**: `src/async_crud_mcp/core/path_validator.py:L47-80, L153-156`

#### Shell Command Validation - Bypass Vulnerability (HIGH)
- **Current**: Pattern-based regex matching susceptible to obfuscation (e.g., `$(echo cat)`, `c''at`)
- **Change**: Implement AST-based parsing to detect command substitution, variable expansion, array construction
- **File**: `src/async_crud_mcp/core/shell_validator.py` (full file refactor)

#### Recycle Bin Restore - Missing Integrity Check (MEDIUM)
- **Current**: Trusts recycle metadata JSON without cryptographic verification
- **Risk**: Malicious metadata modification could restore files to arbitrary locations
- **Change**: Add HMAC-SHA256 signature verification (key derived from server instance ID)
- **File**: `src/async_crud_mcp/core/recycle_bin.py:L191-249`

#### Content Scanner - Baseline Protection (ACCEPTABLE)
- **Current**: Regex-based secret detection (AWS keys, API tokens, private keys)
- **Status**: Adequate baseline but misses obfuscated/encoded secrets - documented limitation only

### Reliability & Infrastructure

#### Hash Contention Detection - Missing Metadata (HIGH)
- **Current**: Returns `ContentionResponse` with diff but no indication of modification source
- **Issue**: Agent cannot distinguish user edit from other agent's change
- **Change**: Add `modified_by: "agent" | "external" | "unknown"` field to `ContentionResponse`, track in lock manager via `request_id`
- **File**: `src/async_crud_mcp/tools/async_update.py:L219-247`

#### Lock Manager - Distributed Scaling (HIGH PRIORITY)
- **Current**: In-memory FIFO queue - single process only, no horizontal scaling
- **Change**: Implement Redis-backed lock manager as alternative to in-memory backend
- **Config**: Add `persistence.lock_backend: "memory" | "redis"` option
- **File**: New file `src/async_crud_mcp/core/lock_manager_redis.py`

#### Search Tool Indexing (MEDIUM)
- **Current**: No index - linear scan on every search
- **Change**: Add optional trigram index built on project activation, stored in `PROJECT_CONFIG_DIR/.search-index/`
- **File**: `src/async_crud_mcp/tools/async_search.py:L104-145`

#### Project Activation (PRESERVED BY DESIGN)
- **Current**: Requires explicit `crud_activate_project()` call before any CRUD operations
- **Status**: User-confirmed correct design - prevents directory confusion if agent changes directories mid-session
- **Reference**: `src/async_crud_mcp/server.py:L213-239`

## Files to Modify

| File | Change |
|------|--------|
| `src/async_crud_mcp/models/requests.py` | Add `RegexPatch` model and `regex_patches` field to `AsyncUpdateRequest` |
| `src/async_crud_mcp/tools/async_update.py` | Add regex substitution logic to patch application loop; add external edit detection to contention response |
| `src/async_crud_mcp/core/path_validator.py` | Default empty `base_directories` to current working directory with warning log |
| `src/async_crud_mcp/core/shell_validator.py` | Implement AST-based command parsing to detect obfuscation techniques |
| `src/async_crud_mcp/core/recycle_bin.py` | Add HMAC-SHA256 signature verification to restore operations |
| `src/async_crud_mcp/core/lock_manager_redis.py` | New file - implement Redis-backed lock manager with config option |
| `src/async_crud_mcp/tools/async_search.py` | Add optional trigram index build and lookup logic |
| `docs/MIGRATION.md` | New file - document glob pattern differences and shell restrictions for agents |

## Verification

1. Run unit tests for regex patch compilation validation: verify invalid patterns rejected before lock acquisition
2. Verify path validator defaults to PWD when `base_directories` is empty, check warning log emitted
3. Test hash contention response includes `modified_by` field correctly populated (agent/external/unknown)
4. Verify shell validator rejects command substitution and obfuscation techniques (at least: `$(...)`, `${}`, empty string splits)
5. Confirm recycle bin restore verifies HMAC signature, rejects tampered metadata files
6. Run performance test on large repo (10k+ files): search with index vs without should show improvement
7. Verify Redis lock manager (if enabled) correctly serializes cross-process file operations vs in-memory baseline
8. Check project activation middleware still enforces explicit `crud_activate_project()` call

## Key Design Decisions

- **Regex editing added not reverted**: Git history (62 commits from 2026-02-12 to 2026-02-23) shows no prior regex support implementation, confirming this is new capability
- **Streaming writes not needed**: User confirmed atomic writes sufficient; no streaming implementation ever existed
- **Shell restrictions by design**: Deny patterns evolved through security hardening over three commits (2026-02-21 to 2026-02-23), never reverted
- **Explicit project activation preserved**: User feedback confirmed this prevents directory confusion for multi-directory agent workflows
- **Recycle bin integrity new feature**: Added in latest commit (2026-02-23); HMAC verification adds missing security layer

## NOT Modified

- **Notebook editing support**: Confirmed other MCP tools handle this
- **LSP integration**: Confirmed other MCP tools handle this
- **Task/process management**: Confirmed other MCP tools handle orchestration
- **Pagination/streaming writes**: Already complete (async_read) or not needed (async_write)

## Execution Order

1. **Phase 1 (Critical blockers)**: Path validation defaults, regex edit support, shell command AST parsing
2. **Phase 2 (High priority)**: Hash contention external edit detection, Redis lock manager, recycle bin signature verification
3. **Phase 3 (Medium)**: Search tool indexing, test coverage for concurrent scenarios
4. **Phase 4 (Low)**: Documentation migration guides

