---
$schema: story-file-v5.1
id: '19'
title: CLI commands (Typer)
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:58.528863+00:00'
updated_at: '2026-02-13T01:59:58.528863+00:00'
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

# Story 19: CLI commands (Typer)

## Description

Implement Typer CLI with subcommand groups: bootstrap, daemon, config, install, setup.

## Acceptance Criteria

- [ ] AC-19.1: bootstrap: install/uninstall/start/stop/status/list
- [ ] AC-19.2: daemon: start/stop/restart/status/logs
- [ ] AC-19.3: config: init/show/edit/validate
- [ ] AC-19.4: install: quick-install and uninstall
- [ ] AC-19.5: setup: Per-user setup wizard (no admin)

## Context

[Background, constraints - optional]
