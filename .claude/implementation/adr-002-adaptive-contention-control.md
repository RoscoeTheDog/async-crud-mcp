# ADR-002: Adaptive Contention Control

**Status:** Proposed — **Phase 4. Build only if contention is observed after ADR-001 Tier 1 ships.**
**Date:** 2026-06-05
**Deciders:** project owner + Claude (session s003)
**Related:** [[adr-001-transactional-edit-engine]], `s003` handoff

---

## Context

Pure OCC (ADR-001) is a **correctness** mechanism, not a **fairness/throughput** one. Under high contention — N agents targeting the same region — agent A queries, B queries, A commits (wins), B is invalidated → re-queries → possibly repeats. Agents burn cycles and may "give up or improvise." OCC has **no notion of queuing or fair distribution** → livelock / starvation under contention.

## Decision

A **three-tier, incrementally-built** strategy. Build cheapest-first; only add the heavy tier on measured need.

### Tier 1 — kill FALSE contention (already in ADR-001)
Region-granular, content-anchored tokens + server-side rebase. Most "conflicts" are two agents editing *different parts* of the same file; with region tokens these **auto-merge**, so livelock becomes rare **without any queuing.** **Ship this first and MEASURE before building Tier 2.**

### Tier 2 — fair FIFO lease for GENUINE same-region contention (this ADR)
When the server **detects** real contention on a region (≥ N conflicting commits on the same anchor within a time window), **escalate that region** from optimistic to a **pessimistic, FIFO, lease-based lock**:
- Agents take a **ticket** + a **short lease**; others **queue in arrival order**.
- **Progress guaranteed** (someone always wins, in order → no livelock).
- **Fairness guaranteed** (FIFO → no starvation).
- **Lease TTL** so a dead/stalled agent can't block forever.
- **Only activates on actually-contested regions** — zero overhead in the common (uncontended) case.

This is adaptive **lock-escalation** (as in mature DBs) and directly eliminates the "give up / improvise" pathology — a contending agent never fails-and-flails; it waits a bounded turn and gets a guaranteed clean window.

### Tier 3 — make contention VISIBLE (optional)
Let `query_replace` return a contention signal ("region hot — you're #3, est. wait Xs"). The agent then chooses: wait, work a different file, or hand back to the orchestrator. Surfacing contention lets agents/orchestrator **self-distribute** → simplifies orchestration.

### Cheap mitigation (always-on)
**Exponential backoff + jitter** on the optimistic retry path so agents don't all retry in lockstep. Reduces livelock probability; **not** a substitute for Tier 2.

## Defense-in-depth (orchestration side)
The simplest robust answer for *structured* work is to **partition** at the orchestrator (disjoint file/region ownership → contention can't arise). Tier 1 auto-merges non-overlapping residue; Tier 2 fairly serializes genuine overlaps. Best practice = **both**: partition to minimize, server absorbs the rest — which moves contention-handling OUT of the orchestrator (the explicit goal).

## Reuse map
- `LockManager` → **extend** to a fair FIFO lease + wait queue. (Today it is a per-file lock for the brief critical section only; there is **no** contention detection / fair queue / work distribution → this is net-new.)
- `background_tasks.py` → lease TTL / expiry.

## Consequences
- A **net-new concurrency subsystem.** Concurrency code in a codebase the audit showed has gaps → it **must** get the adversarial-verify test treatment.
- **Do NOT build before measuring.** Premature fair-queue scheduling is wasted complexity.

## Decision criteria — when to actually build Tier 2
Ship Tier 1; observe real use. Build Tier 2 **only if** the `STALE_CONFLICT` rate on the *same anchor* crosses a threshold (e.g., ≥2 agents repeatedly conflicting on one region within seconds). Otherwise **Tier 1 + backoff/jitter suffices** — leave Tier 2 unbuilt.
