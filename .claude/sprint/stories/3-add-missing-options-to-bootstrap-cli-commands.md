---
$schema: story-file-v5.1
id: '3'
title: Add missing options to bootstrap CLI commands
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:53:22.871523+00:00'
updated_at: '2026-02-13T07:53:22.871523+00:00'
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

# Story 3: Add missing options to bootstrap CLI commands

## Description

The bootstrap_cmd.py is missing several options specified in the spec: install needs --force and --use-task-scheduler options; uninstall needs --username and --force options; start needs --username option; stop needs --username option; status needs --username and --json options; list should show active per-user workers. Also missing admin privilege check and elevation for install/uninstall.

## Acceptance Criteria

- [ ] AC-3.1: install command has --force and --use-task-scheduler options
- [ ] AC-3.2: uninstall command has --username and --force options
- [ ] AC-3.3: start command has --username option
- [ ] AC-3.4: stop command has --username option
- [ ] AC-3.5: status command has --username and --json options
- [ ] AC-3.6: Admin privilege check and elevation for install/uninstall

## Context

[Background, constraints - optional]
