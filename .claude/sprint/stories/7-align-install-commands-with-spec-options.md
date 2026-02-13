---
$schema: story-file-v5.1
id: '7'
title: Align install commands with spec options
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:53:58.735695+00:00'
updated_at: '2026-02-13T07:53:58.735695+00:00'
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

# Story 7: Align install commands with spec options

## Description

The install_cmd.py is missing several spec-required options: quick_install needs --force, --port, --no-start options (currently only has --yes); uninstall needs --keep-config/--remove-config, --keep-logs/--remove-logs, --force options; admin check and elevation for quick-install on Windows is missing. The quick-install flow should install service, generate config, start service, enable daemon. Uses Rich console with fallback.

## Acceptance Criteria

- [ ] AC-7.1: quick_install has --force, --port, --no-start options
- [ ] AC-7.2: uninstall has --keep-config/--remove-config, --keep-logs/--remove-logs, --force options
- [ ] AC-7.3: Admin check and elevation for quick-install on Windows
- [ ] AC-7.4: Uses Rich console for output with fallback

## Context

[Background, constraints - optional]
