---
$schema: story-file-v5.1
id: '2'
title: Complete CLI init with top-level commands and subgroups
type: feature
status: queued
parent: null
created_at: '2026-02-14T01:16:35.149275+00:00'
updated_at: '2026-02-14T01:16:35.149275+00:00'
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

# Story 2: Complete CLI init with top-level commands and subgroups

## Description

The CLI __init__.py registers all subcommand groups but is missing: (1) setup as a direct command (not a subgroup), (2) quick-install and uninstall as top-level commands, (3) version command showing __version__. Currently setup_cmd is registered as a subgroup 'setup' and install_cmd as 'install' subgroup. Per spec, setup should be a direct command, quick-install and uninstall should be top-level, and version should display the package version.

## Acceptance Criteria

- [ ] AC-2.1: setup is a direct top-level command (not a subcommand group)
- [ ] AC-2.2: quick-install is a top-level command
- [ ] AC-2.3: uninstall is a top-level command
- [ ] AC-2.4: version command exists showing __version__ from __init__.py

## Context

[Background, constraints - optional]
