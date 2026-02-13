---
$schema: story-file-v5.1
id: '10'
title: Align paths.py APP_NAME import with ADR-009
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:54:20.359422+00:00'
updated_at: '2026-02-13T07:54:20.359422+00:00'
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

# Story 10: Align paths.py APP_NAME import with ADR-009

## Description

The paths.py imports APP_NAME from ..config which is correct for most purposes but the spec says 'APP_NAME set to async-crud-mcp (ADR-009 single name convention)' as a local constant. The current approach works but could break if config import fails. Also missing XDG_CACHE_HOME support mentioned in spec acceptance criteria. The _is_windows_service_context and _get_user_profile_path are present and correct. Overall well-aligned but needs XDG_CACHE_HOME.

## Acceptance Criteria

- [ ] AC-10.1: XDG compliance includes XDG_CACHE_HOME support on Linux
- [ ] AC-10.2: APP_NAME defined locally as fallback or verified import from config

## Context

[Background, constraints - optional]
