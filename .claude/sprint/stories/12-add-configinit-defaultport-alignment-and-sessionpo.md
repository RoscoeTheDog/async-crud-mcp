---
$schema: story-file-v5.1
id: '12'
title: Add config_init DEFAULT_PORT alignment and session_poll_seconds
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:54:46.408913+00:00'
updated_at: '2026-02-13T07:54:46.408913+00:00'
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

# Story 12: Add config_init DEFAULT_PORT alignment and session_poll_seconds

## Description

The config_init.py has DEFAULT_PORT = 8720 but the spec says the placeholder should be the default port. The spec also mentions session_poll_seconds config parameter in generate_default_config. The current generate_default_config lacks session_poll_seconds. Also init_config is missing the host parameter passthrough.

## Acceptance Criteria

- [ ] AC-12.1: generate_default_config() includes session_poll_seconds
- [ ] AC-12.2: DEFAULT_PORT matches spec default (8422 per target_project or 8720 as current)

## Context

[Background, constraints - optional]
