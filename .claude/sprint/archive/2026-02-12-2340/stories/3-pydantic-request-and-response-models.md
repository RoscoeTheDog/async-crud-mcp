---
$schema: story-file-v5.1
id: '3'
title: Pydantic request and response models
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:50.784247+00:00'
updated_at: '2026-02-13T01:58:50.784247+00:00'
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

# Story 3: Pydantic request and response models

## Description

Create all Pydantic models for MCP tool parameters and responses.

## Acceptance Criteria

- [ ] AC-3.1: Request models for all 11 MCP tools
- [ ] AC-3.2: Patch model with old_string/new_string
- [ ] AC-3.3: Response models for success, error, contention
- [ ] AC-3.4: Diff models for JSON and unified format
- [ ] AC-3.5: Batch response with summary
- [ ] AC-3.6: Mutually exclusive content/patches validation

## Context

[Background, constraints - optional]
