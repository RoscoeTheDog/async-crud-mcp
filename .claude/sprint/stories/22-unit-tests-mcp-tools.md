---
$schema: story-file-v5.1
id: '22'
title: 'Unit tests: MCP tools'
type: feature
status: queued
parent: null
created_at: '2026-02-13T02:00:38.716725+00:00'
updated_at: '2026-02-13T02:00:38.716725+00:00'
depends_on:
- 12
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

# Story 22: Unit tests: MCP tools

## Description

Create unit tests for all individual MCP tools.

## Acceptance Criteria

- [ ] AC-22.1: test_async_read.py: all parameters and error codes
- [ ] AC-22.2: test_async_write.py: all parameters and error codes
- [ ] AC-22.3: test_async_update.py: contention, diff formats, patch applicability
- [ ] AC-22.4: test_async_delete.py: with and without contention check
- [ ] AC-22.5: test_async_rename.py: dual-lock, cross-filesystem
- [ ] AC-22.6: test_async_append.py: all parameters and error codes
- [ ] AC-22.7: test_async_list.py: glob filtering, hash attachment
- [ ] AC-22.8: test_async_batch.py: batch read/write/update, partial failures

## Context

[Background, constraints - optional]
