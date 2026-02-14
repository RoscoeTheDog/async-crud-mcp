---
$schema: story-file-v5.1
id: '4'
title: Add missing options to daemon CLI commands
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:53:29.475232+00:00'
updated_at: '2026-02-13T08:05:04.611123+00:00'
depends_on:
- '2'
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

# Story 4: Add missing options to daemon CLI commands

## Description

The daemon_cmd.py is missing several spec options: start should set daemon.enabled=true in config (currently launches process directly); stop should set daemon.enabled=false (currently unimplemented placeholder); restart should cycle enabled flag with wait; status needs --username, --all, --json options; logs needs --lines, --username, --user options. All commands should use config file mutation (ADR-003) instead of direct process control.

## Acceptance Criteria

- [ ] AC-4.1: start command sets daemon.enabled=true in config (ADR-003)
- [ ] AC-4.2: stop command sets daemon.enabled=false in config
- [ ] AC-4.3: restart command cycles the enabled flag with wait
- [ ] AC-4.4: status command has --username, --all, --json options
- [ ] AC-4.5: logs command has --follow, --lines, --username, --user options
- [ ] AC-4.6: Logs checks ProgramData path for Windows service per-user logs

## Context

[Background, constraints - optional]
