---
$schema: story-file-v5.1
id: '17'
title: Windows service support
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:57.499481+00:00'
updated_at: '2026-02-13T01:59:57.499481+00:00'
depends_on:
- 16
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

# Story 17: Windows service support

## Description

Implement Windows-specific daemon modules: bootstrap_service (pywin32), dispatcher, session_detector.

## Acceptance Criteria

- [ ] AC-17.1: bootstrap_service.py: BUG-01 (ReportServiceStatus first), ADR-011 (manual event loop)
- [ ] AC-17.2: bootstrap_service.py: BUG-07 (try/except with LogErrorMsg)
- [ ] AC-17.3: dispatcher.py: Multi-user dispatch, port conflict detection
- [ ] AC-17.4: dispatcher.py: CREATE_NEW_PROCESS_GROUP
- [ ] AC-17.5: session_detector.py: WTS API session detection

## Context

[Background, constraints - optional]
