---
$schema: story-file-v5.1
id: '7'
title: Diff engine (JSON and unified formats)
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:53.228619+00:00'
updated_at: '2026-02-13T01:58:53.228619+00:00'
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

# Story 7: Diff engine (JSON and unified formats)

## Description

Implement diff computation between file versions for contention responses.

## Acceptance Criteria

- [ ] AC-7.1: JSON diff with change regions (added/removed/modified)
- [ ] AC-7.2: Unified diff format (standard git diff style)
- [ ] AC-7.3: Configurable context lines
- [ ] AC-7.4: Summary with line counts and region count
- [ ] AC-7.5: Uses Python difflib

## Context

[Background, constraints - optional]
