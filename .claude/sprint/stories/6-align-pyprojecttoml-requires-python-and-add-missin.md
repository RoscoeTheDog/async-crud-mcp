---
$schema: story-file-v5.1
id: '6'
title: Align pyproject.toml requires-python and add missing mcp dependency
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:03:07.110077+00:00'
updated_at: '2026-02-17T07:03:07.110077+00:00'
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

# Story 6: Align pyproject.toml requires-python and add missing mcp dependency

## Description

pyproject.toml has requires-python='>=3.12' but spec requires '>=3.10' for broader compatibility. Also missing 'mcp>=1.0.0' from core dependencies per spec AC-d1.3. The ruff target-version should also be updated from py312 to py310 to match.

**Drift Source**: PYPROJECT.template.md
**Max Severity**: minor
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-6.1: requires-python = '>=3.10' in pyproject.toml
- [ ] AC-6.2: mcp>=1.0.0 added to [project.dependencies]
- [ ] AC-6.3: tool.ruff target-version updated from 'py312' to 'py310'
- [ ] AC-6.4: All existing tests still pass with the updated config

## Context

[Background, constraints - optional]
