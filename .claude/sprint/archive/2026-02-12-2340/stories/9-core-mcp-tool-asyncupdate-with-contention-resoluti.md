---
$schema: story-file-v5.1
id: '9'
title: 'Core MCP tool: async_update with contention resolution'
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:21.519937+00:00'
updated_at: '2026-02-13T01:59:21.519937+00:00'
depends_on:
- 7
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

# Story 9: Core MCP tool: async_update with contention resolution

## Description

Implement async_update() with hash-based contention detection and diff-based contention response.

## Acceptance Criteria

- [ ] AC-9.1: Hash comparison for contention detection
- [ ] AC-9.2: Full content replacement mode
- [ ] AC-9.3: Patch mode with old_string/new_string pairs
- [ ] AC-9.4: Contention response with JSON or unified diff
- [ ] AC-9.5: patches_applicable, conflicts, non_conflicting_patches fields
- [ ] AC-9.6: CONTENT_OR_PATCHES_REQUIRED error when neither provided

## Context

[Background, constraints - optional]
