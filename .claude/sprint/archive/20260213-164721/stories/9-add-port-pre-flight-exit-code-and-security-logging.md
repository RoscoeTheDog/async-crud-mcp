---
$schema: story-file-v5.1
id: '9'
title: Add port pre-flight exit code and security logging to server
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:54:12.315325+00:00'
updated_at: '2026-02-13T07:54:12.315325+00:00'
depends_on:
- '8'
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

# Story 9: Add port pre-flight exit code and security logging to server

## Description

The server.py is mostly complete but has gaps: (1) Exit code 48 on EADDRINUSE (port conflict) - currently raises RuntimeError without specific exit code; (2) Localhost binding security: logs security warning for non-localhost binding - missing; (3) Health endpoint should return status, version, uptime as specified.

## Acceptance Criteria

- [ ] AC-9.1: Exit code 48 on EADDRINUSE (port conflict)
- [ ] AC-9.2: Logs security warning for non-localhost binding
- [ ] AC-9.3: Health endpoint returns status, version, uptime

## Context

[Background, constraints - optional]
