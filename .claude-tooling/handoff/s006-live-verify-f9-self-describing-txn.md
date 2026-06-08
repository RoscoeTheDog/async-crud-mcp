# Session 006: Live-Verify F9 (self-describing commit + async_txn_status)

**Status**: COMPLETED (2026-06-07 — all 7 F9 live checks PASS; F9 merged to dev + main)
**Created**: 2026-06-07 18:30
**Skill Version**: context v2.56.0-alpha
**Objective**: Live-verify the F9 changes (self-describing commit response + the new read-only `async_txn_status` tool) against a redeployed :8720 daemon after reconnecting a fresh MCP client, then merge to dev/main.

---

## Reconstruction checkpoint (read this first)

F9 is **implemented, QA-green, committed, and pushed** on branch `s004-live-testing` (commit `e1ddc7d`). It is **not live yet** — the running daemon still serves the pre-F9 code. Live verification must happen in a **fresh session** because MCP tool schemas are cached at connect (the new `async_txn_status_tool` cannot load mid-session).

- **What F9 adds:**
  - `CommitSuccessResponse` gains `applied_match_ids` (exact ids applied — commit is all-or-nothing), `ignored_match_ids` (requested ids no longer staged → exposes silent-drop), `ttl_remaining` (seconds left on an open txn).
  - New read-only tool **`async_txn_status(txn_id)`**: relocates each still-staged match against the live file via the same `rebase_match` logic commit uses; returns current `line`/`col` (content **redacted**), a per-match `locatable` flag predicting commit's apply/stale outcome, plus `current_hash`/`file_changed`/`ttl_remaining`. Derived over the **frozen found-set (never re-scans)**, read-lock only.
- **Two gates before testing (critical):**
  1. **Redeploy** — the live daemon runs from the COPIED install venv `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` (NOT the dev `.venv`). Code goes live only after `scripts\setup.bat` (or `<install-venv>\Scripts\python.exe -m pip install --no-deps <repo>`) + daemon restart. See project memory `[[deployment-topology]]`. The new commit **response fields** need the server restart; the new **tool** needs restart **and** a fresh client.
  2. **Fresh MCP client** — reconnect a new session; confirm `async_txn_status_tool` is present in the tool list.
- **Branch state:** `s004-live-testing` @ `e1ddc7d` (pushed). `dev` and `main` are at `864491f` (the F1–F8 tip) — **one commit behind**, i.e. F9 is NOT yet on dev/main. Merge after live-verify.
- **Test sandbox (isolated):** `C:\Users\Admin\async-crud-livetest\` — external throwaway activated as the daemon project. s005 left files under `...\s005\`; use a fresh `...\s006\` subdir.

---

## Completed (this session, s005 + F9 build)

- **s005 live re-verify of F1–F8** against the redeployed daemon (fresh client): **all 8 PASS**. Recorded in `.claude-tooling/test/s004-livetest-results.md` (commit `864491f`). Fast-forwarded **dev and main** to `864491f` and pushed all three branches.
- **F9 designed + implemented** on `s004-live-testing` (commit `e1ddc7d`):
  - `models/responses.py` — `CommitSuccessResponse` + `applied_match_ids`/`ignored_match_ids`/`ttl_remaining`; new `TxnStatusResponse` + `TxnStatusMatchEntry`.
  - `models/requests.py` — `TxnStatusRequest`; `models/__init__.py` — exports.
  - `core/transaction_manager.py` — `EditTransaction.ttl_remaining` property.
  - `tools/async_txn_status.py` — new read-only tool; `tools/__init__.py` — export.
  - `tools/async_commit.py` — populate the new fields (snapshot staged ids before mutation → ignored set).
  - `server.py` — import + register `async_txn_status_tool`.
  - `tests/test_tools/test_transactional.py` — 8 new F9 tests; `tests/test_server.py` — tool count 26→27.
  - `README.md` — tool inventory + editing-model prose.
- **QA green:** py_compile OK; `ruff --select F` clean on changed files (12 pre-existing F-errors in untouched files only); full suite **845 passed / 10 skipped / 0 failed** (via `run_pytest.py`).
- **Pushed** `s004-live-testing` to origin (`864491f..e1ddc7d`).

---

## Next Steps

- [ ] **Confirm the redeploy landed** — `health_tool` on :8720 (low `uptime_seconds`); `server.log` startup clean (no ERROR/CRITICAL).
- [ ] **Reconnect a FRESH MCP client** — confirm `async_txn_status_tool` appears in the tool list.
- [ ] **Activate sandbox** — `crud_activate_project("C:\\Users\\Admin\\async-crud-livetest")`; confirm `content_scan_enabled: true`. Work under a fresh `...\s006\` subdir.
- [ ] **F9.1 applied_match_ids + ttl** — write a file with 3 uniquely-named matches → `async_query_replace` → `async_commit(match_ids=[2])` → expect `applied_match_ids:[2]`, `remaining_match_ids:[1,3]`, `ttl_remaining > 0`, no `ignored_match_ids`.
- [ ] **F9.2 ignored_match_ids** — on the same open txn, `async_commit(match_ids=[2,3])` (2 already applied) → expect `applied_match_ids:[3]`, `ignored_match_ids:[2]`, `remaining_match_ids:[1]`.
- [ ] **F9.3 txn_status (unchanged file)** — fresh `query_replace` (3 matches) → `async_txn_status(txn_id)` → expect `file_changed:false`, `current_hash == base_hash`, `match_count:3`, `locatable_match_ids:[1,2,3]`, `stale_match_ids:[]`, `ttl_remaining > 0`.
- [ ] **F9.4 txn_status predicts stale** — `query_replace` over a unique-anchored match → make an external ambiguous rewrite (e.g. `async_write` a new file won't do; use `async_update` full-content or a second edit to duplicate the matched text) → `async_txn_status` → expect `file_changed:true`, `stale_match_ids` non-empty, that match's `locatable:false`, `line:null`.
- [ ] **F9.5 txn_status after subset commit** — subset-commit one match → `async_txn_status` → expect `match_count` reduced, remaining ids locatable, `file_changed:true`.
- [ ] **F9.6 redaction** — `query_replace` over a secret (e.g. `AKIA…`) → `async_txn_status` → expect the secret is NOT verbatim in `matches[].before` (shows `<<REDACTED:…>>`), `redactions[]` populated.
- [ ] **F9.7 read-only** — capture file hash (`async_status`), call `async_txn_status`, re-check hash → unchanged; txn still committable afterward.
- [ ] **On all-pass:** record an F9 section in `.claude-tooling/test/s004-livetest-results.md`; merge `s004-live-testing` → `dev` and `main` (fast-forward) and push all three. **On any fail:** record, fix on-branch, re-QA, redeploy, re-verify.

---

## Decisions Made (F9 design)

- **Self-describing, not enforcing.** Every F9 field is informational layered on the unchanged CAS/rebase/all-or-nothing core, so it cannot change conflict outcomes — only what the agent knows before acting. `applied_match_ids == requested subset` because a successful commit applies every selected match (any stale → `stale_conflict`; any protected `before` → `CONTENT_BLOCKED`; nothing partial).
- **`async_txn_status` guardrails (all four honored):** (1) derive remaining preview via `rebase_match` over `txn.matches` — NEVER re-scan (re-scan would surface unstaged occurrences and break the frozen found-set); (2) redact `before`/`after` (egress, like `query_replace`); (3) positions are OPTIMISTIC (snapshot) — only commit-time CAS is authoritative; (4) read-only / read-lock only — no new conflict class.
- **No TTL refresh on subset commit** — kept semantics predictable (txn lives from original query); `ttl_remaining` just exposes the window. A future toggle could refresh on subset commit if desired.
- **`locatable` mirrors commit's location logic** — fast path (file unchanged) uses stored offsets verified by slice-equality; else `rebase_match`. So it predicts per-match commit fate. Caveat: it's a per-match predictor, not a full dry-run (does not run the cross-match `spans_overlap` check).

---

## Context

**Files Modified/Created (s004-live-testing @ e1ddc7d):**
- `src/async_crud_mcp/models/responses.py`, `models/requests.py`, `models/__init__.py`
- `src/async_crud_mcp/core/transaction_manager.py`
- `src/async_crud_mcp/tools/async_txn_status.py` (new), `tools/async_commit.py`, `tools/__init__.py`
- `src/async_crud_mcp/server.py`
- `tests/test_tools/test_transactional.py`, `tests/test_server.py`
- `README.md`

**Documentation Referenced:** `.claude/implementation/adr-001-transactional-edit-engine.md`; README "Editing model"; project memory `deployment-topology.md`.

---

## Blocked

- **F9 live verification cannot begin until (1) the user redeploys** (`scripts\setup.bat` + daemon restart) **and (2) a fresh MCP client reconnects.** The new commit response fields need the server restart; the new `async_txn_status_tool` needs both restart and a fresh client (tool list cached at connect). Until then :8720 serves pre-F9 code.

---

## References

- related_handoffs: `s001, s002, s003, s004, s005`
- source_repo: `C:\Users\Admin\Documents\GitHub\async-crud-mcp`
- working_branch: `s004-live-testing` @ `e1ddc7d` (pushed; tracks `origin/s004-live-testing`)
- integration_branches: `dev` + `main` @ `864491f` (F1–F8 tip; F9 not yet merged)
- commit_this_session: `e1ddc7d` (F9), `864491f` (s005 report)
- remote: `https://github.com/RoscoeTheDog/async-crud-mcp/tree/s004-live-testing`
- live_endpoint: `http://127.0.0.1:8720/sse`
- daemon_logs: `C:\Users\Admin\AppData\Local\async-crud-mcp\logs\`
- install_venv: `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` (copied/non-editable)
- sandbox: `C:\Users\Admin\async-crud-livetest` (use a fresh `s006\` subdir)
- report: `.claude-tooling/test/s004-livetest-results.md`
- qa_result: `full suite 845 passed / 10 skipped / 0 failed`
