---
$schema: story-file-v5.1
id: '10'
title: 'MCP tools: async_delete, async_rename, async_append'
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:22.052592+00:00'
updated_at: '2026-02-13T01:59:22.052592+00:00'
depends_on:
- 8
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

# Story 10: MCP tools: async_delete, async_rename, async_append

## Description

Implement async_delete(), async_rename(), and async_append() MCP tools.

## Acceptance Criteria

- [ ] AC-10.1: async_delete: optional contention check via expected_hash
- [ ] AC-10.2: async_rename: dual-lock in alphabetical order
- [ ] AC-10.3: async_rename: cross-filesystem fallback
- [ ] AC-10.4: async_append: no contention detection, additive semantics
- [ ] AC-10.5: async_append: create_if_missing and separator support

## Context

[Background, constraints - optional]
