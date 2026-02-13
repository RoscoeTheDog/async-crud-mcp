---
$schema: story-file-v5.1
id: '11'
title: Enhance installer.py with full spec features
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:54:41.782885+00:00'
updated_at: '2026-02-13T07:54:41.782885+00:00'
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

# Story 11: Enhance installer.py with full spec features

## Description

The installer.py (scripts/) is a simplified version compared to the spec's ~1100 line requirement. Missing: (1) install subcommand --force/--port options; (2) uninstall subcommand --all option; (3) Privilege checks (admin on Windows); (4) Preflight checks (Python version >= 3.10, disk space, permissions); (5) uv venv --managed-python (ADR-010); (6) pywin32 DLL configuration for Windows Service (GAP-5); (7) Direct CreateService API for service install (GAP-4); (8) Setup wizard and server tests post-install; (9) Exit codes: 0=success, 1=failed, 130=cancelled.

## Acceptance Criteria

- [ ] AC-11.1: install subcommand with --force, --port options
- [ ] AC-11.2: uninstall subcommand with --all option
- [ ] AC-11.3: Checks privileges (admin on Windows)
- [ ] AC-11.4: Preflight checks (Python version >= 3.10, disk space, permissions)
- [ ] AC-11.5: Creates venv with uv venv --managed-python (ADR-010)
- [ ] AC-11.6: Configures pywin32 DLLs for Windows Service (GAP-5)
- [ ] AC-11.7: Exit codes: 0=success, 1=failed, 130=cancelled

## Context

[Background, constraints - optional]
