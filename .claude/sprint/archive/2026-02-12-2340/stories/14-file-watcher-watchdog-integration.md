---
$schema: story-file-v5.1
id: '14'
title: File watcher (watchdog integration)
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:55.901449+00:00'
updated_at: '2026-02-13T01:59:55.901449+00:00'
depends_on:
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

# Story 14: File watcher (watchdog integration)

## Description

Implement OS filesystem watcher using watchdog to detect external file modifications and update hash registry.

## Acceptance Criteria

- [ ] AC-14.1: Watches configured base_directories
- [ ] AC-14.2: Updates hash registry on create/modify/delete events
- [ ] AC-14.3: 100ms debounce for editor save patterns
- [ ] AC-14.4: Coalesces DELETE+CREATE into MODIFY
- [ ] AC-14.5: PollingObserver fallback for network paths and inotify limit
- [ ] AC-14.6: Configurable via watcher config section

## Context

[Background, constraints - optional]
