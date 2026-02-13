---
$schema: story-file-v5.1
id: '12'
title: 'MCP tools: batch operations'
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:23.281491+00:00'
updated_at: '2026-02-13T01:59:23.281491+00:00'
depends_on:
- 9
- 10
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

# Story 12: MCP tools: batch operations

## Description

Implement async_batch_read(), async_batch_write(), async_batch_update() for multi-file operations.

## Acceptance Criteria

- [ ] AC-12.1: batch_read: multiple files in single call
- [ ] AC-12.2: batch_write: multiple new files
- [ ] AC-12.3: batch_update: per-file contention resolution
- [ ] AC-12.4: NOT transactional: partial failures reported per-file
- [ ] AC-12.5: Summary with total/succeeded/failed/contention counts

## Context

[Background, constraints - optional]
