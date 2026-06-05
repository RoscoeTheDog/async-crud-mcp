# ADR-001: Transactional Edit Engine (query → preview → commit)

**Status:** Proposed — implement in **Phase 3** (see handoff `s003`). Extends (does not replace) the one-shot `async_write`/`async_update` tools.
**Date:** 2026-06-05
**Deciders:** project owner + Claude (session s003)
**Related:** `s003` handoff, [[adr-002-adaptive-contention-control]], [[adr-003-filewatcher-and-native-tool-integration]]

---

## Context

The current mutation tools are one-shot. A regex-style replace over a file is **all-or-nothing**: if the pattern matches more than intended, the agent must either (a) craft a narrower regex and re-query, or (b) fall back to many individual edits to avoid clobbering unintended matches. Both are clumsy and re-read the file (extra round-trips).

We want: **preview the matches → select a subset (or hand-edit individual replacements) → commit.** A staged, transactional edit.

Hard constraint: the server is async-safe for **concurrent agents**. If the source file changes between the query (preview) and the commit, the staged result is stale → a race that, handled naively, causes silent corruption or a lost update.

## Decision

A **two-phase staged transactional edit** built on **optimistic concurrency control (OCC / compare-and-swap)**, with **region-granular, content-anchored version tokens** and **server-side rebase/auto-merge**.

### Why OCC, not pessimistic locking
Pessimistic locks would be held across the agent's **think-time** (the query→commit gap is LLM latency — seconds to minutes). Long-held locks across think-time destroy the multi-agent concurrency this server exists for, and a never-committed transaction would deadlock the region until a lease expired. So: **no locks are held during the preview→commit gap.** OCC turns "stale results" from silent corruption into a **detectable, retryable conflict.** Mental model = HTTP **ETag / `If-Match`** (412 on mismatch); same idea as a DB version column or git refusing to push a moved ref.

### Token granularity — the make-or-break choice
Version at the **match-region level, content-anchored** — NOT whole-file, NOT by line number:
- **Whole-file tokens** → any concurrent edit *anywhere* invalidates the transaction (false sharing → constant conflicts for agents editing different parts of one file).
- **Line numbers** shift when other edits insert/delete above.
- **Anchor = hash of the surrounding context window** (the bytes the match replaces + a small before/after window). At commit, validate only that each *selected* match's anchor still matches. A concurrent edit elsewhere does not conflict; only a true overlap does. This is exactly how `git apply` / 3-way merge apply a hunk when its context still matches (with fuzz). **This single decision is what keeps parallel agents from false-conflicting.**

### Protocol (tool surface)
- `query_replace(path, pattern, replacement, [flags])` → `{ txn_id, base_version, matches: [{ match_id, anchor, line, before, after }] }`. Runs the regex, builds a diff **preview**, stages it server-side keyed by `txn_id`. **Does not mutate the file.**
- `amend(txn_id, match_id, new_after)` → override the staged replacement for one match (hand-edit before commit).
- `commit(txn_id, [match_ids])` → re-read file; recompute each selected match's anchor hash; if all still match → apply atomically; else → **`STALE_CONFLICT`** payload listing which matches still apply cleanly vs. which are stale, plus a fresh re-diff. Committing only the selected subset solves the over-match problem.
- `abort(txn_id)` and (optional) `list_transactions()` for hygiene.

### Apply semantics
- **Atomic, all-or-nothing for the selected matches:** compute the full new file content in memory, write via **temp-file + rename** (reuse `file_io`). Never N sequential writes (a crash mid-loop leaves a half-edited file).
- **Server-side rebase / auto-merge:** if the file changed but the selected matches' anchors still match (non-overlapping external edit), apply cleanly — rebased onto current content. Only genuine same-region overlaps return `STALE_CONFLICT`.
- **Pessimistic lock only for the commit critical section** (read → verify → write), via the existing `LockManager` — held for milliseconds, never across think-time.

### Lifecycle & isolation
- Each `txn_id` has a **TTL/lease**; a GC sweep (reuse `background_tasks`) expires abandoned transactions (agents abandon them constantly). Ephemeral is fine — re-query is cheap. If persisted across daemon restart, re-validate `base_version` on resume.
- **Per-user isolation:** a `txn_id` must not cross users — partition by dispatcher worker (`MultiUserDispatcher` already isolates per user).

### Security / egress
- The preview `before`/`after` and the `STALE_CONFLICT` re-diff can contain secrets like any read → route them through `content_scanner` **before egress** (respect `content_scan_metadata` from P1-8).
- Validate the target path with `PathValidator` at commit (same as the CRUD tools); respect the recycle-bin model if an edit deletes content.

### Scope discipline
Keep simple one-shot `write`/`update` for trivial, unambiguous edits. Reserve query→commit for **broad / risky multi-match regex** where preview + subset + CAS actually buys safety. Two-phase-everything is friction.

## Reuse map (build on existing parts — not a rewrite)
| Need | Existing component |
|---|---|
| Version-token source | `HashRegistry` (`core/file_io.py`) |
| Commit critical section (ms) | `LockManager` (`core/lock_manager.py`) |
| Transaction TTL/GC | `background_tasks.py` |
| Atomic apply | `file_io` temp+rename |
| Egress scrub of previews/diffs | `content_scanner` |
| Path safety on commit target | `PathValidator` |
| Per-user txn isolation | `MultiUserDispatcher` (`daemon/dispatcher.py`) |

## Consequences
- The server becomes **more stateful** (transaction store, GC, conflict payloads, `amend`) → more surface to test and secure. Treat the concurrency paths with the **adversarial-verify test discipline** used in the security audit.
- The obfuscation filter's coverage **must** extend to preview diffs (a new egress path).
- Positive: directly mitigates the over-match footgun; gives the agent a **verify-before-apply** step (aligns with the backup-before-trust posture); and the CAS **catches an external/native write** between query and commit (mitigates the dual-file-state hazard in ADR-003).

## Open decisions (resolve during Phase 3 implementation)
- Anchor window size + fuzz tolerance (start ~3 context lines, exact-match; add fuzz only if needed).
- Max matches per transaction (bound memory).
- Whether reads also get a non-CAS handle (a paging convenience, not a correctness need — **defer**).
- `STALE_CONFLICT` payload shape — proposed: `{ matches: [{ match_id, status: applied|stale, new_context }], base_version_new }`.
