---
$schema: story-file-v5.1
id: '23'
title: Integration tests
type: feature
status: queued
parent: null
created_at: '2026-02-13T02:00:39.169976+00:00'
updated_at: '2026-02-13T02:00:39.169976+00:00'
depends_on:
- 13
- 14
- 15
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

# Story 23: Integration tests

## Description

Create integration tests for concurrent agents, contention resolution, external modification, and persistence.

## Acceptance Criteria

- [ ] AC-23.1: test_concurrent_agents.py: simultaneous reads, read-write/write-write contention
- [ ] AC-23.2: test_contention.py: diff accuracy, patch applicability
- [ ] AC-23.3: test_external_modification.py: watcher detects edits, hash updated
- [ ] AC-23.4: test_persistence.py: restart, TTL purge, hash re-validation

## Context

[Background, constraints - optional]
