---
$schema: story-file-v5.1
id: '5'
title: Enhance README with CLI usage examples and two-layer architecture overview
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:02:48.207734+00:00'
updated_at: '2026-02-17T07:02:48.207734+00:00'
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

# Story 5: Enhance README with CLI usage examples and two-layer architecture overview

## Description

README.md is missing explicit CLI command usage examples and the two-layer architecture overview (daemon service + MCP server). The spec requires these sections for user onboarding.

**Drift Source**: README.template.md
**Max Severity**: minor
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-5.1: README contains Quick Install section showing setup.bat / setup.sh usage
- [ ] AC-5.2: README contains CLI usage examples for bootstrap, daemon, config subcommands
- [ ] AC-5.3: README contains Architecture section describing two-layer design (OS service + MCP server)
- [ ] AC-5.4: README describes per-user daemon model and multi-user support

## Context

[Background, constraints - optional]
