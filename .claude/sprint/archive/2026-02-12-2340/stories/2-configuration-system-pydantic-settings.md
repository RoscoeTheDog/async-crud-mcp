---
$schema: story-file-v5.1
id: '2'
title: Configuration system (pydantic-settings)
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:50.175977+00:00'
updated_at: '2026-02-13T01:58:50.175977+00:00'
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

# Story 2: Configuration system (pydantic-settings)

## Description

Implement the pydantic-settings configuration model with daemon, crud, persistence, and watcher sections.

## Acceptance Criteria

- [ ] AC-2.1: Config model has daemon, crud, persistence, watcher sections per PRD Section 5
- [ ] AC-2.2: Environment variable overrides with ASYNC_CRUD_MCP_ prefix
- [ ] AC-2.3: Default values match PRD (port 8720, timeout 30s)
- [ ] AC-2.4: JSON config file loading supported

## Context

[Background, constraints - optional]
