# s004 Live-Test Results — Transactional Edit Engine + Hardened Daemon

**Date:** 2026-06-06
**Branch:** `s004-live-testing` (off `audit-hardening-and-transactional-edits`)
**Live daemon:** `http://127.0.0.1:8720/sse`, version `0.1.0`, 26 tools
**Test sandbox (isolated):** `C:\Users\Admin\async-crud-livetest\` (external throwaway; activated as the daemon project so destructive tools can never reach repo source)
**Tester note:** No source code was modified. Bugs/observations are recorded only. The two `<<REDACTED>>`/secret strings used are fake.

---

## Verdict

The transactional edit engine (ADR-001) and the Phase-1 security hardening **work as designed** in the common cases, and the daemon was **rock-solid**: the entire session produced **0 WARNING/ERROR/CRITICAL records** across a 5140-line `server.log`. Conservative safety invariants (never clobber on conflict; egress redaction; deny-list; path confinement; env-strip) all held.

Eight findings below: **2 worth a real decision** (a write-guard asymmetry between the two regex-replace tools, and a non-recursive audit redaction that can leak secrets into `audit.log`), the rest UX/clarity/info.

---

## Findings (ranked)

### F1 — Write-guard asymmetry: transactional commit bypasses the content-scan write block  [Medium]
`async_update(regex_patches)` runs a **write-time `ContentScanner.scan()` guard**: any regex match whose *matched (old) text* trips a deny rule is **skipped/blocked** (`regex_blocked`), protecting secrets the agent can't even see (reads are redacted). The newer transactional path `async_query_replace` -> `async_commit` has **no equivalent `scan()` guard** — it only `redact()`s the *preview* and then commits freely.

**Proof (identical regex, same file, back-to-back):**
- File `secret_edit_test.txt` line 2 = `api_key = "sk-test-SECRETVALUE..."` (hash `bf10741e`).
- `async_update` regex `api_key = "[^"]*"` -> `api_key = "ROTATED"`: **BLOCKED** — `regex_applied: []`, `regex_blocked: [L2 flagged generic-api-key-assignment]`, hash unchanged.
- `async_query_replace` + `async_commit`, **same regex**: **APPLIED** — hash `bf10741e` -> `a3d40b45`; on-disk line 2 is now `api_key = "ROTATED"`.

**Why it matters:** two tools that both do "regex replace" give different security guarantees. An agent (or prompt-injection) that cannot see a secret can still overwrite/corrupt it via the transactional path. **Decision needed:** mirror the `scan()` write-guard into `async_commit` (scan each staged match's `before` text), or document the intended asymmetry.
**Source:** `tools/async_update.py:314-329` (guard present) vs `tools/async_query_replace.py:103-105` (redact-only) and `tools/async_commit.py` (no scan).

### F2 — Audit redaction is top-level-only / non-recursive -> nested secrets logged verbatim  [Medium]
`server.py:_extract_args_summary` redacts only top-level keys: `_REDACT_ARG_KEYS = {"content","replacement"}` (-> `<N chars>`) and `_REDACT_DICT_ARG_KEYS = {"env"}` (-> `<redacted>`). It does **not** recurse into list/dict args, so secret-bearing payloads nested inside `patches` / `regex_patches` / batch `files[]` are written to `audit.log` in plaintext.

**Proof (raw `audit.log`, daemon-redaction bypassed by reading the file directly):**
- Line 29 — `async_update` logged `"regex_patches": [{"pattern": "api_key = \"[^\"]*\"", "replacement": "api_key = \"ROTATED\""}]` (replacement **not** redacted).
- Line 58 — `async_batch_write` logged `"content": "password = batchsecret123\n"` **verbatim**.
- Contrast (correctly redacted): top-level `async_write` -> `"content": "<94 chars>"`; `async_query_replace` -> `"replacement": "<11 chars>"`; `async_exec` -> `"env": {"ANTHROPIC_API_KEY": "<redacted>", "LD_PRELOAD": "<redacted>"}`.

**Why it matters:** `audit.log` is meant to be the safe-to-keep record; the design comment says content "is never written to the audit log verbatim." That guarantee holds for top-level args but is broken for `async_update(patches/regex_patches)` and `async_batch_write/async_batch_update(files[].content)`. **Decision needed:** make `_extract_args_summary` recurse (redact `new_string`/`replacement`/`content` inside `patches`/`regex_patches`/`files`).
**Source:** `server.py:122-148`.

### F3 — Subset commit consumes the entire transaction  [Low / UX]
After `async_commit(txn, match_ids=[1,2])` applied 2 of 6 matches, a follow-up `async_commit(txn, match_ids=[3,4,5,6])` returned **`TXN_NOT_FOUND`**. A subset commit is single-shot: the remaining staged matches are silently discarded, not retained for a second commit.
**Why it matters:** a caller doing "commit these now, the rest later" loses the rest with no warning. Either document "commit is terminal" or keep the txn open with only the unapplied matches remaining.

### F4 — Directory delete gives a misleading error  [Low / UX]
`async_delete(<directory>)` -> `DELETE_ERROR: [Errno 13] Permission denied`. `async_delete` is **file-only**; directory-tree recycling is actually done by `async_mkdir(path, force=True)` (verified: it recycled the non-empty `to_delete/` tree as `…_to_delete` with `deleted_hash: dir:2_entries` and recreated it empty).
**Why it matters:** "Permission denied" misdirects debugging. Prefer `PATH_IS_DIRECTORY` with a hint to use `mkdir force` (or support recursive delete). The handoff's "directory delete -> recycle" expectation maps to `mkdir force`, not `async_delete`.

### F5 — "Non-overlapping auto-rebase" is narrower than expected (conservative by design)  [Info]
Rebase anchors on **48 characters** of context (`transaction_manager.py:_ANCHOR_WINDOW = 48`) and relocates a match only if the anchored window **or** the matched text appears **exactly once** in the changed file; any ambiguity -> stale "so a commit never clobbers."
- Edit on line 3 (within ~48 chars of matches on lines 1 & 4, where `TARGET` is non-unique) -> **`stale_conflict`, both matches stale, 0 rebased** (and the file was correctly left untouched).
- Edit 14 lines away from a unique `NEEDLE` match -> **`rebased: true`, applied**.

The safety property (never clobber) is correct. But the handoff's "confirm non-overlapping external edits auto-rebase cleanly" only holds when the external edit is **outside every match's ±48-char anchor** *and* the match stays uniquely locatable. Expect more `stale_conflict`s in dense/non-unique cases; the remedy is "re-query."

### F6 — `async_list` does not exclude `.async-crud-mcp` (only `async_search` does)  [Info]
`search.exclude_dirs` (incl. `.async-crud-mcp`) governs **search**, not **list**. Verified: `async_search` for `session_id` (appears 100s of times in `audit.log`) returned **0 matches, files_searched: 11** (audit.log skipped) — recycled/deleted secrets won't be re-found by content search. But `async_list(recursive=true)` **does** enumerate `.async-crud-mcp/logs/audit.log` etc. Existence is visible via list; content reads are still redacted. Probably acceptable; flagging the wording mismatch vs the handoff ("search/list exclude").

### F7 — Read returns redacted content + REAL hash (dual-state) — round-trip hazard  [Info]
`async_read` of a secret file returns `<<REDACTED:rule:n>>` placeholders + a `redactions[]` array, **and the real file hash** (verified: returned hash == `sha256sum` of the real file). This is correct for read-then-edit CAS. Hazard: an agent that does read -> edit the returned string -> `async_update(content=...)` would **persist the `<<REDACTED>>` placeholders**, destroying the secret (the CAS hash would still match). The patch-based update path avoids this; this is the documented dual-state model — worth keeping prominent in tool docs.

### F8 — Zero-match `query_replace` still allocates a txn  [Info]
`async_query_replace` with a pattern that matches nothing returns `match_count: 0` **and a `txn_id`**. Harmless (GC + abort handle it), but a no-op staging could accumulate empty txns under heavy use.

---

## What passed cleanly

**Transactional engine (ADR-001)**
- Preview staging leaves file byte-identical (hash unchanged). [txn `041c…`]
- `async_abort` discards; post-abort commit -> `TXN_NOT_FOUND`. 
- Subset commit applies exactly the selected matches (2 of 6), new hash. [txn `21bae…`]
- Full commit applies all remaining matches. [txn `48221…`]
- `async_amend` overrides one match's replacement; commit applies override + defaults (`RENAMED_CONST` on the amended match, `NEW_CONSTANT` on the rest). [txn `03bb…`]
- `stale_conflict` never writes (file left exactly as the external edit left it). [txn `5050…`]
- Server-side auto-rebase works for a distant, uniquely-locatable match (`rebased: true`). [txn `2b0e…`]
- Bad match_id -> `VALIDATION_ERROR` and the txn is **preserved** (still abortable), i.e. failed commit is non-destructive and retryable.

**Egress redaction**
- `async_read` redacts secrets to `<<REDACTED:rule:id>>` + metadata, hides the value, returns real hash.
- `async_query_replace` preview redacts `before`/`after`.
- `async_search` excludes `.async-crud-mcp` (secret recycle not re-findable).
- `async_exec` env values redacted in audit.

**`async_exec` deny-list + sandbox**
- Denied with correct pattern+reason: `git clean -fdx`, `git reset --hard HEAD`, `truncate -s 0`, `perl -i -pe` (in-place), `cat`.
- Allowed: `echo … && pwd` (ran; cwd defaulted to project root `/c/Users/Admin/async-crud-livetest`).
- **env-strip**: `ANTHROPIC_API_KEY` and `LD_PRELOAD` were stripped **even when explicitly passed via `env`** (`leak=[][]`).

**Path confinement**
- `async_read` outside project root -> `PATH_OUTSIDE_BASE` (repo README unreachable).
- `async_exec` `cwd` outside root -> `PATH_OUTSIDE_BASE`.
- `async_restore` to a destination outside root -> `PATH_OUTSIDE_BASE`.

**Recycle bin**
- File delete -> `recycled: true` + `recycle_name`; `recycle_list` shows original_path/hash/timestamp/size.
- `async_restore` (default destination) restores to original path and consumes the recycle entry.
- Directory recycle via `mkdir force` moves the non-empty tree to recycle (`dir:2_entries`) and recreates empty.
- `recycle_clean(retention_days=0)` removed the tree; recycle list empty; on disk only `.gitignore` + `.manifest.jsonl` remain (**no orphan**).

**General CRUD / batch**
- `read`, `write` (atomic, FILE_EXISTS semantics), `append` (separator honored), `rename` (`cross_filesystem:false`), `mkdir` (auto-parents), `status` (file + global server status: `tracked_files`, locks, queue depth).
- `batch_read` (2/2), `batch_write` (2/2), `batch_update` with **per-file CAS**: correct-hash file applied, wrong-hash file -> `contention/HASH_MISMATCH` with `current_hash` + diff (`succeeded:1, contention:1`).

**Daemon stability**
- `health_tool`: healthy, port listening, Python 3.12.12, disk OK.
- `server.log` (5140 lines): **0 WARNING/ERROR/CRITICAL** records across the whole session, including all denials/conflicts (those log at INFO).

---

## Suggested next actions (for when you're back)
1. Decide on **F1** (mirror the content-scan write-guard into `async_commit`) and **F2** (recurse audit redaction into nested payloads) — both are small, contained changes in `async_commit.py` / `server.py`.
2. Decide on **F3** semantics (terminal subset-commit vs. keep-open) and **F4** error message.
3. F5–F8 are documentation/UX; fold into README "editing model" notes if desired.

**Reproduction:** all sandbox files remain under `C:\Users\Admin\async-crud-livetest\` (with `.async-crud-mcp/logs/audit.log` capturing every call). The branch `s004-live-testing` is unmodified source.
