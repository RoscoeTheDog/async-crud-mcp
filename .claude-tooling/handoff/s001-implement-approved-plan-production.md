# Session 001: Implement Production Readiness Plan for async-crud-mcp

**Status**: COMPLETED
**Created**: 2026-02-23 17:04
**Updated**: 2026-02-24T00:30
**Objective**: Implement approved plan: Production Readiness for async-crud-mcp

---

## Completed

- Planning research completed via /context:PLAN wrapper (2 research passes, 2 reconciliation passes)
- Plan approved by user after iterative refinement (3 discussion rounds)
- Reference table created at `C:/Users/Admin/Documents/GitHub/async-crud-mcp/.claude/subagents/plans/68e7085b-dec7-46c6-a773-dfadfd49dba5-reference.md`
- User feedback incorporated: kept activate_project() behavior, dropped Redis lock manager, dropped trigram indexing, replaced AST shell parsing with stdout/stderr content scanner redaction, added per-match content scanner guard to regex editing
- **Phase 1 (Critical) -- DONE** (commit `987af05`):
  - **1.1 PathValidator secure defaults**: Empty `base_directories` now defaults to CWD instead of allowing all paths. Warning log emitted. 4 new tests.
  - **1.2 Regex editing with content scanner guard**: Added `regex_patches` field to `AsyncUpdateRequest` with `RegexPatch(pattern, replacement, count)` model. Per-match ContentScanner guard blocks flagged matches with position-only error. Response includes `regex_applied`/`regex_blocked` arrays. 10 new tests.
  - **1.3 External edit detection**: Added `modified_by` field ("agent"/"external"/"unknown") to `ContentionResponse` by comparing HashRegistry state against disk hash. Applied to update, delete, and rename tools. 3 new tests.
- **Phase 2 (High priority) -- DONE**:
  - **2.1 Exec stdout/stderr redaction**: Applied `ContentScanner.redact()` to foreground exec output (`async_exec.py`) before returning `ExecSuccessResponse`. Added `content_scanner` parameter (optional, backward-compatible) to `async_exec()` and `_exec_foreground()`.
  - **2.2 Background task wait redaction**: Applied `ContentScanner.redact()` to background task stdout/stderr in `async_wait.py` for both "already completed" and "just completed" paths. Added `content_scanner` parameter to `async_wait()` and `_wait_for_task()`.
  - **2.3 Server wiring**: Passed module-level `content_scanner` to both `async_exec()` and `async_wait()` in `server.py`.
  - 8 new tests (4 exec redaction + 4 wait redaction).
- **Phase 3 (Medium) -- DONE** (commit `76d5eeb`):
  - **3.1 Async-safe RecycleBin**: Added `asyncio.Lock` to `RecycleBin.__init__()`. Converted all 4 public methods (`recycle`, `restore`, `list_entries`, `cleanup`) to `async` with `asyncio.timeout()` + lock acquisition pattern. Each method accepts a `timeout` parameter (default 30s, list_entries 10s). Timeout raises `RecycleBinError`.
  - **3.2 HMAC-SHA256 manifest integrity**: Added `hmac_key: bytes` param to `RecycleBin.__init__()`, `signature: str` field to `RecycleEntry` dataclass, `_compute_signature()` method. Canonical message: `"{recycle_name}:{original_path}:{deleted_hash}:{size_bytes}"`. `recycle()` signs entries before writing manifest. `restore()` verifies HMAC with `hmac.compare_digest()` -- rejects tampered entries, allows unsigned entries (backward compat) with warning log.
  - **3.3 Caller updates**: `server.py` generates ephemeral `os.urandom(32)` HMAC key, passes to `RecycleBin()`. `async_delete.py`, `async_restore.py`, and server tool wrappers now `await` async RecycleBin methods. Added `timeout` field to `AsyncRestoreRequest` model.
  - **3.4 Tests**: All 20 existing tests converted to async. 6 new HMAC integrity tests (signature creation, valid roundtrip, tamper detection for original_path and deleted_hash, unsigned backward compat, different keys). 5 new async locking tests (concurrent recycle, concurrent restore, recycle timeout, restore timeout, same-basename collision). Total: 31 recycle bin tests + 16 delete/restore tool tests = 47/47 passed.
- **Phase 4 (Low) -- DONE** (commit `efccf4e`):
  - **4.1 Migration guide**: `docs/MIGRATION.md` -- maps native Claude Code tools to async-crud-mcp equivalents, documents glob pattern differences (fnmatch vs pathlib.glob), update modes (full/exact/regex), conflict detection, search differences, batch operations, project activation, recycle bin.
  - **4.2 Shell restrictions reference**: `docs/SHELL_RESTRICTIONS.md` -- documents all exec deny patterns by category (file I/O, system commands, interpreter inline-code, command obfuscation, pipe-to-shell, alternate shells, fd redirection), with rationale, recommended alternatives, and content redaction behavior.
- **Phase 5 (Medium-High) -- DONE** (commit `6466205`):
  - **5.1 async_search redact-not-skip**: Replaced `content_scanner.scan()` + `continue` (file-level skip) with `content_scanner.redact()` per-line nulling. Sensitive matched lines get `line_content=None`, `redacted=True`, `redaction_rule` populated. Context lines with sensitive content are individually nulled. `files_with_matches` and `count` modes still include the file/count.
  - **5.2 async_read redact-not-block**: Replaced `content_scanner.scan()` + `ACCESS_DENIED` error with `content_scanner.redact()` in-place placeholder insertion (`<<REDACTED:rule_name:N>>`). Added `redactions: list[RedactionEntry] | None` field to `ReadSuccessResponse`. Offset/limit slicing applies to already-redacted content. `async_batch_read` inherits fix automatically.
  - **5.3 Model changes**: `SearchMatch.line_content` -> `str | None`, `context_before/after` -> `list[str | None]`, added `redacted: bool`, `redaction_rule: str | None`. Moved `RedactionEntry` before `ReadSuccessResponse` to resolve forward reference. Added `ReadSuccessResponse.redactions` field.
  - **5.4 Tests**: 5 new search redaction tests (sensitive line redacted, clean line not redacted, context lines nulled, files_with_matches still returns file, count mode still counts). 4 new read redaction tests (placeholder content, redactions array, offset/limit with redaction, clean file no redactions). Total: 670 passed, 2 pre-existing failures (test_config.py defaults).

---

## Blocked

None

---

## Next Steps

All 5 phases complete. Production readiness plan fully implemented.

### Phase 5: Consistent Content Scanner Redaction (Medium-High)

**Problem**: Content scanner behavior is inconsistent across tools that return file content. Some tools redact sensitive spans in-place (returning position metadata with nulled content), while others skip/block the entire file -- making sensitive files invisible to the LLM even though filenames, structure, and positions are not sensitive.

**Threat model**: Credential exfiltration through LLM context. Server is localhost-only, never public-facing. File names, structure, and match positions are NOT sensitive. Only the literal content of credentials must be withheld.

**Current inconsistency**:

| Tool | Current Behavior | Target Behavior |
|------|-----------------|-----------------|
| async_update (contention) | Redacts spans, returns `RedactionEntry` metadata | Already correct |
| async_update (regex) | Blocks per-match, returns `RegexBlockedMatch` with position | Already correct |
| async_exec / async_wait | Redacts stdout/stderr via `content_scanner.redact()` | Already correct |
| **async_search** | **Skips entire file** (`continue` on `scan_result.blocked`) | **Needs fix** |
| **async_read** | **Blocks entire file** (returns `ACCESS_DENIED` error) | **Needs fix** |
| async_batch_read | Delegates to async_read -- inherits fix automatically | Inherits fix |
| async_list | Never returns content, only names/sizes/timestamps | No change needed |

#### 5.1 async_search -- redact matched lines instead of skipping file

**File**: `src/async_crud_mcp/tools/async_search.py` (lines 136-140)

**Current** (skip pattern):
```python
if content_scanner is not None:
    scan_result = content_scanner.scan(content, str(file_path))
    if scan_result.blocked:
        continue  # entire file invisible
```

**Target** (redact pattern):
- Remove the file-level skip. Instead, after finding a regex match on a line, check if that line contains sensitive content via `content_scanner.redact()`.
- If the matched line has redactions overlapping the match: include the `SearchMatch` but set `line_content` to `null`, add a `redacted: true` flag and `redaction_reason` (rule name).
- Context lines (`context_before`/`context_after`) that contain sensitive content should also be nulled individually (not the whole array -- just the affected lines become `null`).
- For `output_mode="files_with_matches"`: file still appears in results (position not sensitive).
- For `output_mode="count"`: count still incremented (count not sensitive).

**Model changes** (`src/async_crud_mcp/models/responses.py`):
- `SearchMatch.line_content`: Change type from `str` to `str | None`. When redacted, set to `None`.
- `SearchMatch.context_before` / `context_after`: Change type from `list[str]` to `list[str | None]`. Sensitive context lines become `None`.
- Add `SearchMatch.redacted: bool = False` field.
- Add `SearchMatch.redaction_rule: str | None = None` field (rule name that triggered redaction).

**Implementation approach**:
1. Keep reading the file content (don't skip).
2. Use `content_scanner.redact()` on the full file content to get `RedactedContent` with span positions.
3. Build a set of line numbers that have redactions from `RedactedContent.redactions`.
4. When building `SearchMatch` for a line that has redactions: set `line_content=None`, `redacted=True`, `redaction_rule=<first matching rule>`.
5. For context lines, check each against the redacted-lines set, null those that overlap.

#### 5.2 async_read -- redact content instead of blocking file

**File**: `src/async_crud_mcp/tools/async_read.py` (lines 82-93)

**Current** (block pattern):
```python
if content_scanner is not None:
    scan_result = content_scanner.scan(content, str(validated_path))
    if scan_result.blocked:
        return ErrorResponse(
            error_code=ErrorCode.ACCESS_DENIED,
            message=f"File contains sensitive content matching rule '{scan_result.matched_pattern}' (line {scan_result.matched_line})",
            path=request.path,
        )
```

**Target** (redact pattern):
- Replace `scan()` with `redact()` (same as async_update contention path already does).
- Replace sensitive spans in the returned content with `<<REDACTED:rule_name:N>>` placeholders.
- Add `redactions: list[RedactionEntry] | None` field to `ReadSuccessResponse`.
- When redactions exist, populate the field with position metadata (id, rule_name, line, col_start, original_length) -- same `RedactionEntry` model already used by `ContentionResponse`.

**Model changes** (`src/async_crud_mcp/models/responses.py`):
- Add `ReadSuccessResponse.redactions: list[RedactionEntry] | None = None` field.

**Implementation approach**:
1. Replace the `scan()` + block with `redact()`.
2. If `redacted_result.has_redactions`: use `redacted_result.content` as the file content (placeholders already inserted), build `RedactionEntry` list from spans.
3. Offset/limit slicing applies to the already-redacted content (placeholders are part of the text).
4. `async_batch_read` inherits this automatically since it delegates to `async_read`.

#### 5.3 Tests

**New tests needed**:
- `tests/test_tools/test_async_search.py`: Search in file with sensitive content -- verify match returned with `line_content=None`, `redacted=True`, `redaction_rule` populated. Verify context lines nulled appropriately. Verify `files_with_matches` mode still returns the file. Verify `count` mode still counts.
- `tests/test_tools/test_async_read.py`: Read file with sensitive content -- verify content returned with `<<REDACTED:...>>` placeholders. Verify `redactions` array populated with correct positions. Verify offset/limit still works with redacted content.

#### Implementation notes

- The `RedactionEntry` model already exists in `responses.py` (line 244) -- reuse it for `ReadSuccessResponse`.
- `ContentScanner.redact()` already returns `RedactedContent` with `content` (placeholders inserted) and `redactions` (list of `RedactionSpan` with id, rule_name, line, col_start, col_end, original_length) -- no new scanner work needed.
- The update tool's contention path (`async_update.py` lines 161-176) is the reference implementation for the redact pattern -- follow the same `RedactedContent` -> `RedactionEntry` mapping.
- `SearchMatch.line_content` becoming nullable is a breaking schema change for consumers that expect `str`. Consider whether to version or just document.
- `async_list` does NOT need changes -- it never returns file content.

---

## Decisions Made

- **Keep activate_project()**: Auto-activation from PWD rejected because agent directory changes would cause incorrect project root detection
- **Regex editing with content scanner guard**: Per-match scanning -- clean matches applied and returned with text, flagged matches skipped and returned with position-only error (anti-exfiltration). Agent gets applied/blocked arrays in response.
- **Exec stdout/stderr redaction over AST shell parsing**: Threat model is exfiltration (credentials read back to LLM), not local execution. Apply ContentScanner.redact() to exec output instead of hardening command input parsing. Zero agent friction.
- **Drop Redis lock manager**: Single-machine architecture sufficient. Adds complexity without current need.
- **Drop trigram search indexing**: Introduces staleness/reliability issues in write-heavy multi-agent workloads. Index rebuild on restart causes lag. Rapid file changes create bottleneck (sync updates slow writes, async updates serve stale results). Linear scan is always correct.
- **async_write stays atomic**: 256MB limit is generous. No streaming needed.
- **async_read pagination already exists**: offset/limit parameters with response metadata already implemented.
- **Missing features (Notebook, LSP, Task) non-blocking**: Other MCP tools handle these.
- **Redact-not-skip for content scanner**: All tools that return file content should redact sensitive spans with position metadata instead of skipping/blocking entire files. Filenames, structure, and match positions are not sensitive -- only literal credential content must be withheld. Localhost-only threat model (credential exfiltration via LLM context).
- **async_list excluded from redaction**: Never returns file content, only names/sizes/timestamps. No change needed.

---

## Errors Resolved

None

---

## Context

**Commit History**:
- `987af05` feat(security): implement Phase 1 critical production readiness features (10 files, +549/-32)
- `d27968e` feat(security): redact sensitive data from exec stdout/stderr (Phase 2)
- `76d5eeb` feat(security): add HMAC integrity and async-safe locking to recycle bin (Phase 3)
- `efccf4e` docs: add migration guide and shell restrictions reference (Phase 4)
- `68b78d9` refactor(list): switch async_list from fnmatch to pathlib.glob

**Files Modified in Phase 1**:
- `src/async_crud_mcp/core/path_validator.py` (secure CWD default)
- `src/async_crud_mcp/models/requests.py` (RegexPatch model, regex_patches field)
- `src/async_crud_mcp/models/responses.py` (RegexAppliedMatch, RegexBlockedMatch, modified_by field)
- `src/async_crud_mcp/models/__init__.py` (exports)
- `src/async_crud_mcp/tools/async_update.py` (regex patch logic, content scanner guard, modified_by detection)
- `src/async_crud_mcp/tools/async_delete.py` (modified_by detection)
- `src/async_crud_mcp/tools/async_rename.py` (modified_by detection)
- `src/async_crud_mcp/server.py` (regex_patches parameter on tool endpoint)
- `tests/test_path_validator.py` (4 new tests)
- `tests/test_tools/test_async_update.py` (13 new tests)

**Files Modified in Phase 2**:
- `src/async_crud_mcp/tools/async_exec.py` (content_scanner param, stdout/stderr redaction)
- `src/async_crud_mcp/tools/async_wait.py` (content_scanner param, task output redaction)
- `src/async_crud_mcp/server.py` (wire content_scanner to exec and wait)
- `tests/test_tools/test_async_exec.py` (4 new redaction tests)
- `tests/test_tools/test_async_wait.py` (4 new redaction tests)

**Files Modified in Phase 3** (commit `76d5eeb`):
- `src/async_crud_mcp/core/recycle_bin.py` (asyncio.Lock, HMAC signing/verification, async methods, timeout)
- `src/async_crud_mcp/server.py` (os.urandom HMAC key, await async recycle bin calls)
- `src/async_crud_mcp/tools/async_delete.py` (await recycle_bin.recycle())
- `src/async_crud_mcp/tools/async_restore.py` (await recycle_bin.restore(), pass timeout)
- `src/async_crud_mcp/models/requests.py` (timeout field on AsyncRestoreRequest)
- `tests/test_core/test_recycle_bin.py` (converted to async, +11 new HMAC/locking tests)

**Files Added in Phase 4** (commit `efccf4e`):
- `docs/MIGRATION.md` (tool mapping, glob differences, update modes, search comparison)
- `docs/SHELL_RESTRICTIONS.md` (deny pattern reference by category)

**Test Results**: 47/47 recycle bin + delete/restore tests passed. 1 pre-existing failure in test_config.py (config default mismatch from prior sprint).

**Plan Files**:
- `.claude/subagents/plans/68e7085b-dec7-46c6-a773-dfadfd49dba5-plan.md` (research file)
- `.claude/subagents/plans/68e7085b-dec7-46c6-a773-dfadfd49dba5-presentation.md` (presentation summary)
- `.claude/subagents/plans/68e7085b-dec7-46c6-a773-dfadfd49dba5-reference.md` (reference table)
