---
$schema: story-file-v5.1
id: '1'
title: Align pyproject.toml with spec build layout
type: feature
status: queued
parent: null
created_at: '2026-02-14T01:16:06.815311+00:00'
updated_at: '2026-02-14T01:16:06.815311+00:00'
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

# Story 1: Align pyproject.toml with spec build layout

## Description

The pyproject.toml is missing the src layout configuration required by the spec. The build system should be configured for hatchling with src layout explicitly. The psutil dependency is in [project.optional-dependencies].dev instead of a separate dev section. Entry point exists and most deps are correct.

## Acceptance Criteria

- [ ] AC-1.1: Build system configured for hatchling with explicit src layout (packages = ["src/async_crud_mcp"] already present, verify wheel targets)

## Context

[Background, constraints - optional]
