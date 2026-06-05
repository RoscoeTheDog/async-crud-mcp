# ADR-003: FileWatcher Resolution & Native-Tool Integration Notes

**Status:** Proposed — **Phase 2 decisions** (resolves handoff items P2-2, P2-3).
**Date:** 2026-06-05
**Deciders:** project owner + Claude (session s003)
**Related:** [[adr-001-transactional-edit-engine]], `s003` handoff. Audit findings: `file-watcher-never-started`, `docs-drift-tool-count`, `read-then-edit-friction`.

---

## P2-2 — FileWatcher: start it, or remove it?

**Finding (`file-watcher-never-started`):** `core/file_watcher.py` implements a full `FileWatcher` (debounce + HashRegistry integration), exported from `core/__init__.py`, but it is **never instantiated or started** anywhere. `WatcherConfig` exists but is unused. External edits (git checkout, native Write, another process) are discovered only **reactively**, when `async_update` hits a hash mismatch.

**Decision:** The transactional engine (ADR-001) relies on the **commit-time CAS hash check**, NOT the watcher, for staleness detection. The watcher is therefore **not required for correctness.** Two options:

- **(a) START it** — gated by `WatcherConfig.enabled` (default off), to proactively refresh the `HashRegistry` on external edits. Nicer UX (fewer surprise conflicts), at the cost of a running watcher and **feedback-loop risk** (it reacts to the agent's own writes; needs debounce / self-write suppression — the impl already has debounce).
- **(b) REMOVE it** — delete `file_watcher.py` + `WatcherConfig`. Less code, less surface; the reactive CAS handles staleness, which is sufficient.

**Recommendation: (b) remove for now.** The audit showed the codebase already has gaps; dead code is surface that must be either wired correctly or deleted, and the reactive CAS is enough. If proactive invalidation is wanted later, re-introduce it **with** the transactional engine and an explicit self-write-suppression test. **Either way, act deliberately — do not leave it dead.**

## P2-3 — Docs drift & native-tool friction

### Docs drift (`docs-drift-tool-count`)
README claims **"11 CRUD tools"**; the server exposes **~28** (9 CRUD + 3 batch + 3 recycle + 3 shell + 3 config + health + …). **Decision:** update the README to a **categorized, accurate tool inventory** (or move the extension tools — `exec`/`wait`/`search`, config — into a clearly-labeled "extensions" section). Keep it in sync as the transactional tools (ADR-001) land.

### read-then-edit friction (`read-then-edit-friction`)
`async_update` requires `expected_hash` from a prior `async_read` — incompatible with native "just edit" semantics; agents mixing native and server tools get surprised. **Decision:**
- **Document** the read → hash → update pattern prominently.
- The transactional engine (ADR-001) **generalizes** this (the CAS token replaces the manual hash dance); steer multi-match / risky edits there.
- Consider an optional **`force=True`** on `async_update` that bypasses the hash check (accepting lost-update risk) for agents that want native-like semantics.

### Dual file-state hazard (with Claude's native Read-before-Edit)
The harness tracks file state for its native `Edit`; this server tracks its own via `HashRegistry`. **Decision / guidance:** within the server, `HashRegistry` + CAS is the source of truth; cross-tool, the **commit-time CAS catches a native write** that happened between query and commit. **Operational rule to document (README + ADR-001):** on a given file, use **EITHER** the server's tools **OR** native tools for a mutation sequence — do not interleave them mid-edit.

---

## Sequencing summary (for whoever implements)
1. **Phase 2 (design — this set of ADRs): DONE** once these three files exist.
2. **Phase 3:** implement ADR-001 Tier 1 (transactional edits + region tokens + rebase). Resolve P2-2 (remove or wire FileWatcher) and P2-3 (README + friction docs) alongside.
3. **Phase 4:** implement ADR-002 Tier 2 (adaptive FIFO-lease) **only if** measured contention warrants it.
