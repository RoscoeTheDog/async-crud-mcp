---
$schema: story-file-v5.1
id: '20'
title: Installation scripts
type: feature
status: queued
parent: null
created_at: '2026-02-13T02:00:21.804387+00:00'
updated_at: '2026-02-13T02:00:21.804387+00:00'
depends_on:
- 13
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

# Story 20: Installation scripts

## Description

Create platform installer scripts: shell wrappers, stdlib installer, uninstaller, uv bootstrap, build_installer, configure_claude_code, test_server.

## Acceptance Criteria

- [ ] AC-20.1: setup.bat: Windows wrapper delegating to installer.py
- [ ] AC-20.2: setup.sh: Unix wrapper delegating to installer.py
- [ ] AC-20.3: installer.py: stdlib-only, install/uninstall/menu
- [ ] AC-20.4: uninstaller.py: stdlib-only cleanup
- [ ] AC-20.5: bootstrap_uv.py: Cross-platform uv bootstrap
- [ ] AC-20.6: build_installer.py: Python Embedded Bundle builder
- [ ] AC-20.7: configure_claude_code.py: Adds to Claude Desktop MCP config
- [ ] AC-20.8: test_server.py/bat/sh: Post-install verification

## Context

[Background, constraints - optional]
