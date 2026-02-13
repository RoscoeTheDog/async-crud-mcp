---
$schema: story-file-v5.1
id: '1'
title: Project scaffold and pyproject.toml
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:58:20.693071+00:00'
updated_at: '2026-02-13T01:58:20.693071+00:00'
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

# Story 1: Project scaffold and pyproject.toml

## Description

Create pyproject.toml with all dependencies, package metadata, entry points, and the base package structure.

## Acceptance Criteria

- [ ] AC-1.1: pyproject.toml has name=async-crud-mcp, requires-python>=3.12
- [ ] AC-1.2: All runtime dependencies from PRD Section 6 listed
- [ ] AC-1.3: Dev dependencies in optional-dependencies
- [ ] AC-1.4: src/async_crud_mcp/__init__.py exports __version__
- [ ] AC-1.5: src/async_crud_mcp/__main__.py supports python -m invocation
- [ ] AC-1.6: All subpackage __init__.py files created

## Context

[Background, constraints - optional]
