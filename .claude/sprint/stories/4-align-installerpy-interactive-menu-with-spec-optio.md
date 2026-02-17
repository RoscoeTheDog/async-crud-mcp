---
$schema: story-file-v5.1
id: '4'
title: Align installer.py interactive menu with spec options
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:02:30.318810+00:00'
updated_at: '2026-02-17T07:02:30.318810+00:00'
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

# Story 4: Align installer.py interactive menu with spec options

## Description

scripts/installer.py interactive menu shows Install/Uninstall/Test/Exit but spec expects Install/Reinstall/Uninstall/Quit as the four menu options. Align the menu items: rename 'Test' to 'Reinstall' (with stop+reinstall+restart logic), rename 'Exit' to 'Quit', and reorder to match spec ordering (1=Install, 2=Reinstall, 3=Uninstall, 4=Quit).

**Drift Source**: INSTALLER.template.md
**Max Severity**: minor
**Classification**: partial

## Acceptance Criteria

- [ ] AC-4.1: Interactive menu option 1 is 'Install'
- [ ] AC-4.2: Interactive menu option 2 is 'Reinstall' which stops existing service, reinstalls, and restarts
- [ ] AC-4.3: Interactive menu option 3 is 'Uninstall'
- [ ] AC-4.4: Interactive menu option 4 is 'Quit' (replaces 'Exit')

## Context

[Background, constraints - optional]
