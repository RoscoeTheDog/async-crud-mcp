# Session 003: Audit Remediation + Transactional-Edit Engine

**Status**: ACTIVE — PREP/SCAFFOLD ONLY (implementation NOT started; halt requested by user)
**Created**: 2026-06-05
**Updated**: 2026-06-05
**Objective**: Remediate the confirmed security audit findings, then add a transactional (query->commit) edit model with adaptive multi-agent contention control. This session consolidated branches and produced this plan; **no implementation code written yet.**

> Origin note: this session ran from cwd `C:\Users\Admin\Desktop` (non-git). Handoff intentionally placed in THIS repo (`.claude/handoff/`, continuing s001/s002) per user instruction, not the global handoff location. Driving session id: `0cad333b` (Desktop project).

---

## Reconstruction checkpoint (read this first)

**Git state (done this session):**
- Consolidated hierarchically with fast-forward merges: `patch-installation-setup -> dev` (`9be3385..f5eea37`), `dev -> main` (`50f1610..f5eea37`). Pushed both.
- **`main` == `dev` == `f5eea37`** ("feat(safety): recycle existing content before destructive overwrites").
- Deleted merged leaf `patch-installation-setup` (local `-d` + remote). Pruned. No parallel leaves remain.
- **Working branch: `audit-hardening-and-transactional-edits`** (cut from `dev`). All work below lands here.
- Untracked housekeeping junk in tree: `.claude/subagents/`, `.claude/test-output*.txt` — candidates for `.gitignore`.

**Audit provenance:** a 4-dimension adversarial audit ran via the Workflow tool (run `wf_a1720887-282`, 31 agents). 27 raw findings -> **22 confirmed, 5 refuted** after per-finding verification. The 5 refuted (= confirmed-SAFE): no recursive hard-delete (os.unlink fails on dirs), no symlink-swap TOCTOU (realpath resolves first), exec stdout/stderr IS redacted, search context IS redacted per-line, HashRegistry read-design is sound. Raw output was at a temp path (ephemeral) — the actionable findings are inlined in Phase 1 below, so this file is self-sufficient.

**Two user gates that remain in force:**
1. **Backup-before-live-testing.** Do NOT restart/redeploy the live daemon or exercise its delete tools against real data until the user confirms a system backup. Writing code + tests on the branch is fine; *running the server live is not* until cleared.
2. **content_scan_enabled defaults true** (good) but is per-project disableable via `crud_update_config` — verify it stays on for any trading/crypto project.

---

## Phased TODO (living checklist — update boxes as we go)

### Phase 1 — Security remediation (do FIRST; small, urgent, reviewable)
- [x] **P1-1 (CRITICAL) exec deny-list bypass.** ✅ DONE (7f0a107). `config.py` `_default_deny_patterns()` (~L218-300) does not block `git clean -fdx` / `git reset --hard` / `git checkout --force`, `truncate`, `perl -i`/`ruby -i`, or `xxd|od|hexdump >`. These delete/modify files straight past the recycle-bin model. Add deny patterns; **strongly consider migrating exec to an allow-list** (3 separate bypass classes trace to deny-list leakiness). Findings: `git-clean-bypass`, `truncate-unblocked`, `inplace-file-editors-bypass`, `printf-write-not-universally-blocked`.
- [x] **P1-2 (CRITICAL) restore escapes base_directories.** ✅ DONE (0c0c856). `recycle_bin.restore()` (~L259-260, L272) uses `original_path` from the manifest WITHOUT `path_validator` when `destination=None`; unsigned manifest entries are allowed (warn-and-proceed). Always `path_validator.validate_operation(restore_to, 'write')` before the move; pass the validator into `restore()`; reject unsigned/out-of-root entries. Findings: `unvalidated-manifest-restore`, `unvalidated-manifest-original-path`, `recycle-restore-no-path-validation`, `restore-destination-not-revalidated-on-overwrite`.
- [x] **P1-3 (HIGH) audit log leaks secrets.** ✅ DONE (9ad3e9e). `server.py` `_extract_args_summary()` (~L115-121) logs the `env` dict and sub-200-char `content` UNREDACTED to `.async-crud-mcp/logs/audit.log` (redaction never touches the audit pipeline). Redact all `env` values; replace `content` with a `<N chars>` placeholder regardless of size. **Top trading-secret exposure** (mnemonics/exchange keys). Findings: `audit-env-unfiltered`, `write-content-never-scanned`.
- [x] **P1-4 (HIGH) deleted secrets resurface.** ✅ DONE (7624c51). `SearchConfig.exclude_dirs` (config.py ~L358-374) omits `.async-crud-mcp`, so recycled files (incl. deleted `.env`) are re-found by `async_search`/`async_list`. Add `.async-crud-mcp` to default excludes. Finding: `recycle-dir-searchable-by-agent`.
- [x] **P1-5 (HIGH) directory recycle leaks disk.** ✅ DONE (0b21b24). `recycle_bin.recycle()` moves dirs via `shutil.move` (L178) but `cleanup()` uses `os.unlink` (L429) which fails silently on dirs -> orphaned trees linger forever. Detect `is_dir()`; use `shutil.rmtree` in cleanup. Finding: `directory-recycle-via-shutil-move`.
- [x] **P1-6 (HIGH) unbounded exec output.** ✅ DONE (7624c51 + ce2d7e8). No `max_output_size_bytes`; `async_exec.py` drain loops (~L175-219) extend bytearrays without bound -> RAM exhaustion DoS within the timeout window (also in `background_tasks.py`). Add `max_output_size_bytes` (default ~50MB) to `ShellConfig`; enforce in drain. Findings: `unbounded-output-buffers`, `no-max-output-size`.
- [x] **P1-7 (HIGH) silent activation gate.** ✅ DONE (f36058b) — gate returns structured `error_code: NO_PROJECT_ACTIVATED` + `structured_content` so agents can detect-and-auto-activate. Every non-exempt tool hard-fails until `crud_activate_project` is called (`server.py` ProjectActivationMiddleware). Improve UX: prominent docs + optional auto-activate-to-cwd flag. Finding: `silent-activation-requirement`.
- [x] **P1-8 (MED) redaction metadata.** ✅ DONE (3004490 + f36058b) — `content_scan_metadata` flag gates secret type/position; default on (back-compat), set False for trading projects. `RedactionEntry` (`async_read.py` L94-103, `async_search.py` L194-204) returns `rule_name`+line+col+length, revealing secret type/location. Gate behind a per-project flag (default off for trading). Finding: `redaction-metadata-leaks-position`.
- [x] **P1-9 (LOW) exec env re-injection guard.** ✅ DONE (ce2d7e8). Add a validator rejecting `request.env` keys that appear in `shell_config.env_strip` (currently safe via strip-after-merge, but defense-in-depth). Finding: `env-var-injection-in-request-env`.

### Phase 2 — Design (ADR) before building the feature
- [x] **P2-1 Write the ADR** ✅ DONE — ADR-001 (transactional edits) + ADR-002 (adaptive contention) in `.claude/implementation/`. for the transactional-edit engine + adaptive contention control. Decisions already settled (see "Decisions" below). Place under `.claude/implementation/` (precedent: `shell-extension-plan.md`).
- [x] **P2-2 Resolve `FileWatcher` dead code.** ✅ DECIDED in ADR-003 (recommend REMOVE; execute during Phase 3). Fully implemented but never instantiated/started (`file_watcher.py`); external edits aren't proactively tracked. Decide: start it in `_server_lifespan` (gated by `WatcherConfig.enabled`) OR delete it. Note: the transactional CAS must rely on the commit-time hash check, NOT the watcher. Finding: `file-watcher-never-started`.
- [x] **P2-3 Docs drift + native-tool friction.** ✅ DECIDED in ADR-003 (README inventory fix + read-then-edit/dual-state guidance; execute during Phase 3). README claims 11 tools; 28 exist (`docs-drift-tool-count`). `async_update` requires an `expected_hash` from a prior read — friction vs native Read/Edit (`read-then-edit-friction`). Capture both in the ADR/README.

### Phase 3 — Tier 1: transactional edits (the part that kills most livelock)
- [ ] `query_replace(path, pattern, replacement)` -> `{txn_id, matches:[{match_id, anchor, before, after}], base_version}` (diff preview).
- [ ] Region-granular, **content-anchored** version tokens (anchor = hash of surrounding context window, NOT line numbers). Reuse the existing `HashRegistry`.
- [ ] `commit(txn_id, match_ids)` = re-read, CAS against token; apply atomically (temp+rename); on mismatch return `STALE_CONFLICT` + fresh re-diff. `amend(txn_id, match_id, new_after)` for hand-editing staged replacements.
- [ ] **Server-side rebase/auto-merge**: non-overlapping concurrent edits apply cleanly (git-apply-style context match); only true same-line overlaps conflict.
- [ ] Transaction TTL/lease + GC (use `background_tasks`); per-user isolation (don't let `txn_id` cross dispatcher workers).
- [ ] Egress: route preview `before`/`after` through `content_scanner` (a staged diff can contain a secret like any read).
- [ ] Keep simple one-shot `write`/`update` for trivial edits; reserve query->commit for broad/risky multi-match regex.

### Phase 4 — Tier 2: adaptive contention (build only if contention is observed)
- [ ] Contention detection (N conflicting commits on a region within a window) -> escalate that region from optimistic to **pessimistic FIFO lease-based lock**.
- [ ] Lease TTL (dead-agent safety), fair ticketed queue -> progress + fairness guarantees (kills the "give up / improvise" pathology).
- [ ] Backoff + jitter on the optimistic retry path.
- [ ] Optional: contention/intent signal in the query response ("region hot, you're #3") so agents/orchestrator self-distribute.
- [ ] Defense-in-depth note: orchestrator should still partition work to MINIMIZE contention; the server absorbs the residue.

---

## Decisions Made (this session)

- **Branch model:** fast-forward consolidation `patch -> dev -> main` (history was linear; chose FF to make all branches identical/current). Deleted the merged feature branch local+remote to eliminate parallel leaves.
- **Sequencing:** security fixes (Phase 1) BEFORE the transactional feature — the audit gaps (esp. exec bypass + restore) undermine the safety the feature would otherwise rely on.
- **Concurrency model for the feature:** **optimistic CAS, not pessimistic locking.** Pessimistic locks held across LLM think-time would kill the multi-agent concurrency the server exists for. OCC turns the user's "stale results" race into a detectable, retryable conflict.
- **Token granularity:** region-level, content-anchored (NOT whole-file, NOT line-number). Whole-file tokens cause false-sharing conflicts between agents editing different parts; region tokens + server-side rebase make most concurrent edits auto-merge.
- **Contention handling is adaptive:** optimistic by default; escalate ONLY contested regions to a fair FIFO lease. Moves contention-handling into the server to simplify orchestration (user's explicit goal).
- **Exec hardening direction:** prefer allow-list over patching the deny-list (three bypass classes confirmed leaky).
- **Handoff location:** in-repo `.claude/handoff/` (override of the global skill default) because session cwd was the Desktop.

---

## Next Steps

1. **Phase 1 COMPLETE — all 9 done, suite-verified (672 passed / 10 skipped).** ✅ P1-1 `7f0a107`, P1-2 `0c0c856`, P1-3 `9ad3e9e`, P1-4 `7624c51`, P1-5 `0b21b24`, P1-6 `7624c51`+`ce2d7e8`, P1-7 `f36058b`, P1-8 `3004490`+`f36058b`, P1-9 `ce2d7e8`. Branch pushed to `origin/audit-hardening-and-transactional-edits`. **Phase 2 design COMPLETE — all ADRs front-loaded** (hedge against compaction): ADR-001 (transactional edits), ADR-002 (adaptive contention), ADR-003 (FileWatcher + integration) in `.claude/implementation/`. **Phase 3 IN PROGRESS:** **3a core+models DONE** (`e60c54d`) — `core/transaction_manager.py` (CAS fast-path + content-anchored `rebase_match` + `apply_spans`, per-user TTL store) and Query/Commit/Amend/Abort request + response models (`ErrorCode.TXN_NOT_FOUND`); unit-verified 14/14, full suite green (672/10). **Next 3b:** the 4 tools (`async_query_replace`/`commit`/`amend`/`abort`) reading/writing under `LockManager` with `content_scanner` egress-scrub + `PathValidator` + atomic `atomic_write`, registered in `server.py` with a global `TransactionManager` (wire through the activation + audit middleware), plus `models/__init__.py` re-exports and integration tests. **Then:** P2-2 (remove dead `FileWatcher` per ADR-003) + P2-3 (README tool inventory + friction docs). **Phase 4** (ADR-002 Tier 2 fair-lease) only if measured contention warrants.
2. Continue Phase 1 items as small, individually-committed, suite-verified fixes. QA recipe: `uv sync --extra dev` then `run_pytest.py --json -v --process-timeout 200 --timeout=60 -c <repo>/pyproject.toml --rootdir <repo> <repo>/tests` (use `--json -v`; `-q` loses output to the IOCP teardown hang).
3. Then P2-1 ADR -> Phase 3 -> Phase 4.
4. Reminder: do not deploy/live-test the daemon until the user confirms a backup.

---

## Context / References

- **Audit run:** Workflow `wf_a1720887-282` (driving session `0cad333b`, Desktop project). 22 confirmed / 5 refuted. Findings inlined in Phase 1 (raw output was ephemeral temp).
- **Prior handoffs:** `s001` (production readiness, C1-C?), `s002` (pre-deployment audit C1-C12, all complete — this is the work now on `f5eea37`).
- **Key source files to touch (Phase 1):** `src/async_crud_mcp/config.py` (deny patterns L218-300, exclude_dirs L358-374, ShellConfig L303-345), `src/async_crud_mcp/core/recycle_bin.py` (restore L259-312, recycle L178, cleanup L429), `src/async_crud_mcp/server.py` (`_extract_args_summary` L115-121, activation middleware), `src/async_crud_mcp/tools/async_exec.py` (drain L175-219).
- **Feature-relevant existing infra:** `HashRegistry` (`core/file_io.py`) = the CAS token source; `LockManager` (`core/lock_manager.py`) = the short commit critical section; `background_tasks.py` = txn GC; `MultiUserDispatcher` (`daemon/dispatcher.py`) = per-user isolation.
- **Test baseline:** s002 reported 137/137 passing; suite is now **672 passed / 10 skipped** post-Phase-1.
- **Design ADRs (front-loaded for Phases 2-4):** `.claude/implementation/adr-001-transactional-edit-engine.md`, `adr-002-adaptive-contention-control.md`, `adr-003-filewatcher-and-native-tool-integration.md`.
