# Session 005: Live-Re-Verify F1–F8 Fixes Against Redeployed Daemon

**Status**: ACTIVE
**Created**: 2026-06-07 13:22
**Skill Version**: context v2.56.0-alpha
**Objective**: Live-re-verify the F1–F8 fixes against the redeployed :8720 daemon after reconnecting a fresh MCP client.

---

## Reconstruction checkpoint (read this first)

The s004 live test is done and **all 8 findings are fixed/resolved, committed, and pushed** on branch `s005`'s parent `s004-live-testing`. The remaining work is **live re-verification against the running daemon** — but the fixes are **not yet live until the user finishes redeploying** (they were redeploying via `scripts\setup.bat` when this handoff was written).

- **Deploy model (critical):** the live daemon runs from the **COPIED, non-editable** install venv at `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` — NOT the editable dev `.venv`. Code fixes only go live after `scripts\setup.bat` (or `<install-venv>\Scripts\python.exe -m pip install --no-deps <repo>`) + daemon restart. See project memory `[[deployment-topology]]`.
- **Fresh-client gate (critical):** an MCP client caches the tool list **and tool param schemas** at connect time. The new `allow_redaction_markers` param and the new response fields only appear to a **newly connected** client. Reconnect before testing.
- **Branch:** `s004-live-testing` (pushed, tracks `origin/s004-live-testing`). Off parent `audit-hardening-and-transactional-edits`. Not merged to dev/main.
- **Test sandbox (isolated):** `C:\Users\Admin\async-crud-livetest\` — an external throwaway activated as the daemon project so destructive tools never reach repo source. Its `.async-crud-mcp/logs/audit.log` captured every s004 call.

---

## Completed

- **s004 live test** of the deployed transactional engine + hardened daemon (26 tools) against the isolated sandbox. 8 findings recorded in `.claude-tooling/test/s004-livetest-results.md`.
- **All 8 findings triaged with the maintainer and resolved** on `s004-live-testing`:
  - **F1** (commit bypassed content-scan write guard) + **F2** (audit redaction not recursive) — commit `2b0fbb9`.
  - **F3** (subset commit consumed whole txn) + **F4** (dir delete → misleading error) + **F8** (zero-match allocated a txn) — commit `375ae8b`.
  - **F7** (redacted-content write-back hazard) guard + **F5/F6** README docs — commit `b14f5e7`.
  - Report resolution-status table — commit `1367ce6`.
- **QA green throughout:** `py_compile` + `ruff --select F` clean on changed files; full suite **837 passed / 10 skipped / 0 failed** (via `run_pytest.py` wrapper).
- **Branch pushed to origin** as backup (tracking `origin/s004-live-testing`).
- Transient pytest log files cleaned from the tree.

---

## Next Steps

- [ ] **Confirm the redeploy landed**
  - Run `health_tool` on `:8720`; verify `version`/low `uptime_seconds` reflect a fresh restart.
  - Check `C:\Users\Admin\AppData\Local\async-crud-mcp\logs\server.log` startup lines (no ERROR/CRITICAL).
- [ ] **Reconnect a FRESH MCP client** before any verification (tool/param schemas are cached at connect). Confirm `async_write_tool`/`async_update_tool` now expose `allow_redaction_markers`.
- [ ] **Activate the sandbox**: `crud_activate_project("C:\\Users\\Admin\\async-crud-livetest")` (or a fresh sandbox dir). Confirm `content_scan_enabled: true`.
- [ ] **F1 live** — `async_query_replace` over a secret line → `async_commit` → expect `CONTENT_BLOCKED`, file untouched, txn still abortable.
- [ ] **F2 live** — `async_batch_write` with a fake secret in `files[].content` AND `async_update` `regex_patches[].replacement` carrying a secret → read raw `audit.log` via Bash (daemon read would redact) → expect `<N chars>`/`<redacted>`, **no verbatim secret**.
- [ ] **F3 live** — `async_query_replace` with 3 uniquely-named matches → `async_commit(match_ids=[2])` → expect `txn_id` + `remaining_match_ids=[1,3]` present (txn open) → `async_commit(match_ids=[1,3])` → expect `rebased: true`, all applied.
- [ ] **F4 live** — `async_delete` on a directory → expect `IS_A_DIRECTORY` with the `async_mkdir(force=True)` hint.
- [ ] **F7 live** — `async_read` a redacted file, then `async_update(content=<that redacted text>)` / `async_write` → expect `REDACTION_MARKERS_PRESENT`; retry with `allow_redaction_markers=true` → ok. Confirm `patches` path still works.
- [ ] **F8 live** — `async_query_replace` with a non-matching pattern → expect `match_count: 0`, **no** `txn_id`.
- [ ] **On all-pass**: consider opening a PR / merging `s004-live-testing` → dev/main per project flow. **On any fail**: record in the report, fix on-branch, re-QA (`run_pytest.py`), redeploy, re-verify.

---

## Decisions Made

- **F1 is all-or-nothing**: `async_commit` refuses the whole commit (`CONTENT_BLOCKED`) and **preserves the txn** if any selected match's `before` text is egress-protected — chosen over `async_update`'s per-match silent skip to keep the txn model clean and pair with F3 keep-open.
- **F3 keep-open relies on the existing rebase path**: after a subset commit the txn keeps the unapplied matches with their original anchors; the next commit relocates them by content anchor (positions re-derived, never stale offsets). The found set is **never re-scanned**, so replacements that introduce new pattern occurrences don't expand the txn.
- **F5 docs-only**, **F6 leave `async_list` behavior** (metadata-only; documented), **F7 guard on full-content paths only** with `allow_redaction_markers` override (patches unaffected — and the cheaper edit path).
- **F2 redaction is recursive but key-scoped**: only write-payload keys (`content`, `replacement`, `new_string`) and `env` are scrubbed at any depth; match specifiers (`pattern`, `old_string`) stay in the clear for audit context.

---

## Context

**Files Modified/Created (s004-live-testing branch)**:
- `src/async_crud_mcp/tools/async_commit.py` — F1 content-scan write guard + F3 keep-open (txn_id/remaining_match_ids).
- `src/async_crud_mcp/tools/async_query_replace.py` — F8 (no txn on zero match).
- `src/async_crud_mcp/tools/async_delete.py` — F4 (`IS_A_DIRECTORY`).
- `src/async_crud_mcp/tools/async_write.py`, `async_update.py` — F7 redaction-marker write guard.
- `src/async_crud_mcp/tools/async_batch_write.py`, `async_batch_update.py` — F7 `allow_redaction_markers` passthrough.
- `src/async_crud_mcp/core/content_scanner.py` — `contains_redaction_placeholder()`; `core/__init__.py` — export.
- `src/async_crud_mcp/core/transaction_manager.py` — `set_matches()` (F3).
- `src/async_crud_mcp/models/responses.py` — ErrorCodes `CONTENT_BLOCKED`/`IS_A_DIRECTORY`/`REDACTION_MARKERS_PRESENT`; `CommitSuccessResponse.txn_id`+`remaining_match_ids`; `QueryReplaceResponse.txn_id` optional.
- `src/async_crud_mcp/models/requests.py` — `allow_redaction_markers` on write/update + batch items.
- `src/async_crud_mcp/server.py` — F2 recursive `_extract_args_summary`/`_redact_args`; thread `content_scanner` into `async_commit`; `allow_redaction_markers` tool params.
- Tests: `tests/test_tools/test_transactional.py`, `test_async_delete.py`, `test_async_write.py`, `test_async_update.py`, `tests/test_server.py`.
- `README.md` — F5/F6/F7 editing-model docs.
- `.claude-tooling/test/s004-livetest-results.md` — report + F1–F8 resolution table.

**Documentation Referenced**: `.claude/implementation/adr-001-transactional-edit-engine.md`; README "Editing model" section; project memory `deployment-topology.md`.

---

## Blocked

- **Live re-verification cannot begin until the user finishes the redeploy** (`scripts\setup.bat` + daemon restart) **and a fresh MCP client reconnects.** Until then the running `:8720` daemon still serves the pre-fix code and the cached (old) tool schemas. Verify both before running the F1–F8 live checks.

---

## References

- related_handoffs: `s001, s002, s003, s004`
- source_repo: `C:\Users\Admin\Documents\GitHub\async-crud-mcp`
- working_branch: `s004-live-testing` (pushed; tracks `origin/s004-live-testing`)
- parent_branch: `audit-hardening-and-transactional-edits`
- commits_this_session: `2b0fbb9, 375ae8b, b14f5e7, 1367ce6`
- remote: `https://github.com/RoscoeTheDog/async-crud-mcp/tree/s004-live-testing`
- live_endpoint: `http://127.0.0.1:8720/sse`
- daemon_logs: `C:\Users\Admin\AppData\Local\async-crud-mcp\logs\`
- install_venv: `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` (copied/non-editable)
- sandbox: `C:\Users\Admin\async-crud-livetest`
- report: `.claude-tooling/test/s004-livetest-results.md`
- qa_result: `full suite 837 passed / 10 skipped / 0 failed`
