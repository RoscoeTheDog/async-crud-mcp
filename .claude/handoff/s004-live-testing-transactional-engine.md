# Session 004: Live-Test Transactional Edit Engine + Hardened Daemon

**Status**: ACTIVE
**Created**: 2026-06-06 16:35
**Skill Version**: context v2.56.0-alpha
**Objective**: Live-test the deployed transactional edit engine + security-hardened daemon (26 tools) against real files. All code is done, merged on the branch, and **deployed live**; backup is complete.

---

## Reconstruction checkpoint (read this first)

**Everything is built, verified, and DEPLOYED LIVE.** This session is for *exercising* the running daemon, not writing features.

- **Working branch:** `audit-hardening-and-transactional-edits` (async-crud-mcp), pushed to origin. Not yet merged to dev/main.
- **Live daemon:** serves SSE on `http://127.0.0.1:8720/sse` with **26 tools** (was 22 pre-Phase-3). Redeployed 2026-06-06 16:23 via `scripts\setup.bat` (force reinstall) + verified from the live process's startup log.
- **Backup gate: CLEARED** — user completed a system backup before redeploy. Live testing (incl. delete/exec tools against real data) is now authorized.
- **Phases 1-3 complete; Phase 4 deferred by design** (adaptive fair-lease — build only if contention is observed).
- **Deploy model (important):** the live daemon runs from a **COPIED, non-editable** install at `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` (NOT the dev repo `.venv`, which is editable). So **any code fix made during testing needs a redeploy** (`scripts\setup.bat`, or `<install-venv>\Scripts\python.exe -m pip install --no-deps <repo>`) + daemon restart before it goes live. See project memory `[[deployment-topology]]`.

---

## Completed (this session, picking up from s003)

- **Phase 3c cleanup** (`b4ea868`): removed dead `FileWatcher` + `WatcherConfig` (+ inert `watcher` section from `crud_get_config`); README tool inventory 11->26 + read-then-edit/dual-state docs.
- **run_pytest "undercount" root-caused + fixed** (`fa7a661`): it was a REAL Windows ProactorEventLoop teardown hang (`BackgroundTaskRegistry.shutdown()` cancelled background tasks without awaiting them -> orphaned subprocess pipe -> `GetQueuedCompletionStatus` hang -> pytest-timeout aborted at ~663/831), NOT output truncation. Fixed: shutdown() awaits cancelled tasks; `background_registry` fixtures await shutdown() on teardown.
- **run_pytest.py hardened to v1.1.0** (claude-code-tooling `dev` @ `6f257c49`, deployed to `~/.claude`): reports `incomplete`/exit 2 instead of false-green when a run is killed before pytest's summary line; added `--output PATH`.
- **Transaction GC sweep wired** (`54e83d5`): `_txn_gc_loop` in `_server_lifespan` prunes expired transactions every 300s -> **closes the last Phase 3 gap**.
- **Handoff s003 updated** (`93065c4`) to reflect the above and correct its stale QA note.
- **Full suite COMPLETES: 821 passed / 10 skipped (831 collected) in ~19s, 0 failed.**
- **Redeployed + verified live** (26 tools, GC sweep running, FileWatcher/WatcherConfig gone) on `:8720`.

---

## Next Steps (the live-test plan)

1. **Connect a FRESH MCP client to `:8720`** and confirm **26 tools** appear. Look specifically for the 4 new transactional tools: `async_query_replace_tool`, `async_commit_tool`, `async_amend_tool`, `async_abort_tool`. (A client caches its tool list at connect time, so the new tools only show in a *new* connection.)
2. **Activate a project first** via `crud_activate_project` (project root). Non-exempt tools hard-fail with `NO_PROJECT_ACTIVATED` until activated (health + activate are exempt).
3. **Exercise the transactional flow** (ADR-001):
   - `async_query_replace(path, pattern, replacement)` -> inspect the `txn_id` + per-match diff preview (file unchanged).
   - `async_commit(txn_id, match_ids=subset)` then a full commit; confirm atomic apply + new hash.
   - `async_amend(txn_id, match_id, replacement)` then commit; confirm the override applied.
   - `async_abort(txn_id)`; confirm discard.
   - **Stale-conflict path:** query -> edit the file externally -> commit -> expect `STALE_CONFLICT` with `stale_match_ids`/`applicable_match_ids` (and confirm non-overlapping external edits auto-rebase cleanly).
   - **Egress redaction:** put a secret in a match's surrounding context; confirm the preview redacts it (per-project `content_scan_enabled`).
4. **Spot-check the Phase-1 security fixes live** (the reason the feature waited on them):
   - `async_exec` deny-list: `git clean -fdx`, `git reset --hard`, `truncate`, in-place editors should be blocked; allow-listed reads pass.
   - `async_restore` rejects out-of-root / unsigned manifest destinations.
   - Audit log (`audit.log`) redacts `env` values and replaces `content` with a `<N chars>` placeholder.
   - `async_search`/`async_list` exclude `.async-crud-mcp` (recycled files, incl. deleted `.env`, not re-found).
   - Directory delete -> recycle -> `recycle_clean` actually removes the tree (no orphan).
5. **General CRUD/batch/recycle** smoke test (read/write/update/append/rename/mkdir/list/status, batch_*, restore/recycle_list/recycle_clean).
6. **Watch the daemon logs** while testing: `C:\Users\Admin\AppData\Local\async-crud-mcp\logs\server.log` + `audit.log`.

---

## Decisions Made (carry forward)

- **Phase 4 (adaptive contention / fair-lease) is intentionally NOT built** — optimistic CAS + server-side rebase handles the common case; escalate to fair-lease only if real contention is measured.
- **Transaction GC**: 300s sweep interval; lazy on-access expiry (`TransactionManager.get`) already covers correctness, the sweep just bounds memory for abandoned transactions.
- **run_pytest reliability**: with v1.1.0, `incomplete:true`/exit 2 = a real mid-run abort to investigate, NOT a count floor. QA recipe: `uv sync --extra dev` then `run_pytest.py --json --process-timeout 400 --timeout=60 -c <repo>/pyproject.toml --rootdir <repo> <repo>/tests` -> expect `complete:true`, 821/10.
- **Deploy is copied/non-editable** -> code fixes during testing require a redeploy + restart. Optional one-time switch to editable (`pip install --no-deps -e <repo>`) would make future deploys restart-only.

---

## Gates still in force

- **content_scan_enabled stays ON** for any trading/crypto project (per-project disableable via `crud_update_config`; default true). Verify it stays on before testing against sensitive data.
- (Backup gate is CLEARED.)

---

## Context

**Files Modified/Created (this session)**:
- `src/async_crud_mcp/server.py` — Phase 3c (crud_get_config watcher removal, docstring 11->26) + `_txn_gc_loop`/`_txn_gc_task` GC sweep in lifespan
- `src/async_crud_mcp/config.py`, `src/async_crud_mcp/core/__init__.py` — `WatcherConfig`/`FileWatcher` removed
- `src/async_crud_mcp/core/background_tasks.py` — `shutdown()` awaits cancelled tasks (hang fix)
- `tests/test_tools/test_async_exec.py`, `tests/test_tools/test_async_wait.py` — `background_registry` async yield-fixtures awaiting shutdown()
- `tests/test_config.py`, `tests/test_server.py` — watcher refs removed
- `README.md` — tool inventory + editing-model docs
- Deleted: `src/async_crud_mcp/core/file_watcher.py`, `tests/test_file_watcher.py`
- `.claude/handoff/s003-*.md` + `INDEX.md` — updated
- claude-code-tooling: `components/runtime/resources/claude-runtime/scripts/run_pytest.py` (v1.1.0, on `dev`)

**Key files for live-test reference**: `src/async_crud_mcp/server.py` (26 tools + lifespan), `src/async_crud_mcp/tools/async_query_replace.py` / `async_commit.py` / `async_amend.py` / `async_abort.py`, `src/async_crud_mcp/core/transaction_manager.py`, design ADRs in `.claude/implementation/adr-00{1,2,3}-*.md`.

**Documentation Referenced**: `.claude/implementation/adr-001-transactional-edit-engine.md` (transactional design), `DEPLOY.md` (claude-code-tooling runtime), project memory `deployment-topology.md`.

---

## References

- related_handoffs: `s001, s002, s003`
- source_repo: `C:\Users\Admin\Documents\GitHub\async-crud-mcp`
- working_branch: `audit-hardening-and-transactional-edits`
- commits_this_session: `b4ea868, fa7a661, 93065c4, 54e83d5`
- tooling_repo: `C:\Users\Admin\Documents\GitHub\claude-code-tooling` (run_pytest v1.1.0 on `dev` @ `6f257c49`)
- live_endpoint: `http://127.0.0.1:8720/sse`
- daemon_logs: `C:\Users\Admin\AppData\Local\async-crud-mcp\logs\`
- install_venv: `C:\Users\Admin\AppData\Local\async-crud-mcp\venv` (copied/non-editable)
