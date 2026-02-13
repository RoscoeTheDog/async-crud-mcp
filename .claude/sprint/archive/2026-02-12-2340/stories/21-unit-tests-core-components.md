---
$schema: story-file-v5.1
id: '21'
title: 'Unit tests: core components'
type: feature
status: queued
parent: null
created_at: '2026-02-13T02:00:38.314382+00:00'
updated_at: '2026-02-13T02:00:38.314382+00:00'
depends_on:
- 5
- 6
- 7
- 14
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

# Story 21: Unit tests: core components

## Description

Create unit tests for lock_manager, file_io, diff_engine, file_watcher, and path_validator.

## Acceptance Criteria

- [ ] AC-21.1: conftest.py with shared fixtures
- [ ] AC-21.2: test_lock_manager.py: lock semantics, FIFO, timeout, TTL, dual-lock
- [ ] AC-21.3: test_file_io.py: atomic writes, hash, encoding, append
- [ ] AC-21.4: test_diff_engine.py: JSON diff, unified diff, edge cases
- [ ] AC-21.5: test_file_watcher.py: debouncing, hash registry, events

## Context

[Background, constraints - optional]
