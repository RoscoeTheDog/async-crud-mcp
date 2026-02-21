---
$schema: story-file-v5.1
id: '11'
title: Fix installer service install and add post-install steps
type: feature
status: queued
parent: null
created_at: '2026-02-14T01:21:46.968745+00:00'
updated_at: '2026-02-14T01:21:46.968745+00:00'
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

# Story 11: Fix installer service install and add post-install steps

## Description

The installer.py install_service() looks for a non-existent service_installer.bat. Per template spec, it should use venv python to call CLI 'bootstrap install' (same pattern as template's step_install_service). Also missing post-install steps: running setup wizard and server tests. NOTE: Several spec ACs are ALREADY DONE from earlier fixes: privileges check, preflight checks, uv venv --managed-python, pywin32 DLL config, exit codes, menu (4 options), error handling, uv pip install.

## Acceptance Criteria

- [ ] AC-11.1: install_service() uses venv python -m async_crud_mcp bootstrap install instead of non-existent service_installer.bat
- [ ] AC-11.2: Runs setup wizard post-install via venv python -m async_crud_mcp setup --no-interactive
- [ ] AC-11.3: Runs server tests post-install via test_server.py
- [ ] AC-11.4: Logging to installer.log file for debugging
- [ ] AC-11.5: InstallerContext or step tracking for clear progress reporting

## Context

[Background, constraints - optional]
