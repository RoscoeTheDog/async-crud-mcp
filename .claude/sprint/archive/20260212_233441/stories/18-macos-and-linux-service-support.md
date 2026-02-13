---
$schema: story-file-v5.1
id: '18'
title: macOS and Linux service support
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:57.949242+00:00'
updated_at: '2026-02-13T01:59:57.949242+00:00'
depends_on:
- 16
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

# Story 18: macOS and Linux service support

## Description

Create macOS LaunchAgent plist + installer and Linux systemd service unit + installer.

## Acceptance Criteria

- [ ] AC-18.1: macOS: Valid launchd plist pointing to async-crud-mcp
- [ ] AC-18.2: macOS: launchd_installer.sh manages launchctl load/unload
- [ ] AC-18.3: Linux: Valid systemd user service unit
- [ ] AC-18.4: Linux: systemd_installer.sh manages systemctl enable/start

## Context

[Background, constraints - optional]
