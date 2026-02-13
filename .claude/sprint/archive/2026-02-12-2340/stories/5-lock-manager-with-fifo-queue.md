---
$schema: story-file-v5.1
id: '5'
title: Lock manager with FIFO queue
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:52.012629+00:00'
updated_at: '2026-02-13T01:58:52.012629+00:00'
depends_on:
- 1
blocks: []
cross_story_impact: []
affected_by: []
deferred_reason: null
deferred_at: null
validation:
  status: null
  runs: 0
  latest_artifact: null
  active_remediation: null
---

# Story 5: Lock manager with FIFO queue

## Description

Implement per-file read/write lock manager with FIFO queue semantics.

## Acceptance Criteria

- [ ] AC-5.1: Per-file asyncio-based read/write locking
- [ ] AC-5.2: FIFO queue ordering per file
- [ ] AC-5.3: Concurrent reads allowed (shared lock)
- [ ] AC-5.4: Exclusive writes block reads and other writes
- [ ] AC-5.5: Timeout handling returns LOCK_TIMEOUT
- [ ] AC-5.6: Starvation prevention
- [ ] AC-5.7: TTL-based expiry for persistence mode
- [ ] AC-5.8: Alphabetical lock ordering for dual-lock

## Context

[Background, constraints - optional]
