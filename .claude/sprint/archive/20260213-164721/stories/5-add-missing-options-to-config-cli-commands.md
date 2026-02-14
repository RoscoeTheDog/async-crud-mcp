---
$schema: story-file-v5.1
id: '5'
title: Add missing options to config CLI commands
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:53:32.793234+00:00'
updated_at: '2026-02-13T07:53:32.793234+00:00'
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

# Story 5: Add missing options to config CLI commands

## Description

The config_cmd.py is missing several options from the spec: init command needs --port, --no-interactive, and --username options; show command needs --username and --json options; validate should use pydantic model validation.

## Acceptance Criteria

- [ ] AC-5.1: init command has --port, --no-interactive, --username options
- [ ] AC-5.2: show command has --username and --json options
- [ ] AC-5.3: validate command uses pydantic model validation

## Context

[Background, constraints - optional]
