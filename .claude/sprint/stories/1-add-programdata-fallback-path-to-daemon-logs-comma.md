---
$schema: story-file-v5.1
id: '1'
title: Add ProgramData fallback path to daemon logs command
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:01:20.387037+00:00'
updated_at: '2026-02-17T07:01:20.387037+00:00'
depends_on: []
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

# Story 1: Add ProgramData fallback path to daemon logs command

## Description

The daemon logs command in daemon_cmd.py does not check the ProgramData fallback path on Windows when the primary log path is not found. Per spec d24 AC-d24.5, when running in Windows service context (LocalSystem), logs may be written to %PROGRAMDATA%/async-crud-mcp/logs instead of the user's LOCALAPPDATA path. The logs command should check this alternate location.

**Drift Source**: CLI_COMMANDS.template.md (Daemon Commands)
**Max Severity**: minor
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-1.1: daemon logs command checks ProgramData fallback path on Windows when primary log path not found
- [ ] AC-1.2: ProgramData path uses PROGRAMDATA environment variable with async-crud-mcp/logs suffix
- [ ] AC-1.3: Fallback only triggers on win32 platform

## Context

[Background, constraints - optional]
