---
$schema: story-file-v5.1
id: '15'
title: Persistence layer
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:56.464286+00:00'
updated_at: '2026-02-13T01:59:56.464286+00:00'
depends_on:
- 5
- 6
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

# Story 15: Persistence layer

## Description

Implement optional state persistence for hash registry and pending queue entries.

## Acceptance Criteria

- [ ] AC-15.1: Persists file hash registry to DATA_DIR/state.json
- [ ] AC-15.2: Persists pending queue entries (metadata only)
- [ ] AC-15.3: TTL-based purge of expired entries on startup
- [ ] AC-15.4: Re-validates hashes against disk files on startup
- [ ] AC-15.5: Debounced writes (at most once per second)
- [ ] AC-15.6: Enabled/disabled via configuration

## Context

[Background, constraints - optional]
