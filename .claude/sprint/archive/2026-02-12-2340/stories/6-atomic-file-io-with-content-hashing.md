---
$schema: story-file-v5.1
id: '6'
title: Atomic file I/O with content hashing
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:52.673588+00:00'
updated_at: '2026-02-13T01:58:52.673588+00:00'
depends_on:
- 4
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

# Story 6: Atomic file I/O with content hashing

## Description

Implement atomic file operations and SHA-256 content hashing with cross-platform guardrails.

## Acceptance Criteria

- [ ] AC-6.1: Atomic writes via mkstemp + fsync + os.replace
- [ ] AC-6.2: SHA-256 hashing in sha256:<hex> format
- [ ] AC-6.3: Retry with backoff for Windows PermissionError
- [ ] AC-6.4: Cross-filesystem rename fallback
- [ ] AC-6.5: fsync on parent directory for Linux
- [ ] AC-6.6: Hash raw bytes (no line ending normalization)

## Context

[Background, constraints - optional]
