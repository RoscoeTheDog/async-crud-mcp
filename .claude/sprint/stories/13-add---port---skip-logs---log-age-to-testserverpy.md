---
$schema: story-file-v5.1
id: '13'
title: Add --port, --skip-logs, --log-age to test_server.py
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:55:44.446581+00:00'
updated_at: '2026-02-13T08:05:05.604674+00:00'
depends_on:
- '9'
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

# Story 13: Add --port, --skip-logs, --log-age to test_server.py

## Description

The scripts/test_server.py is missing CLI options specified in spec: --port for custom port, --skip-logs to skip log file age check, --log-age for max log age. Currently it hardcodes port 8765 and has no log age checking. Also needs clear pass/fail output improvement.

## Acceptance Criteria

- [ ] AC-13.1: --port option for custom port
- [ ] AC-13.2: --skip-logs option to skip log file age check
- [ ] AC-13.3: --log-age option for max log age
- [ ] AC-13.4: Clear pass/fail output

## Context

[Background, constraints - optional]
