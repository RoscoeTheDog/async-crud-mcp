---
$schema: story-file-v5.1
id: '6'
title: Align setup wizard with spec steps
type: feature
status: queued
parent: null
created_at: '2026-02-14T01:18:50.539806+00:00'
updated_at: '2026-02-14T01:18:50.539806+00:00'
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

# Story 6: Align setup wizard with spec steps

## Description

The setup_cmd.py has a wizard but does not follow the spec's 6-step flow. Missing: --port, --no-interactive, --force options on the setup command itself; Step 1 prerequisites check; Step 2 auto-discover port if default in use; Step 5 configure Claude Code CLI; Step 6 verify server connectivity. Currently the wizard flow mixes config init and service install but misses the per-user directory creation, Claude Code configuration, and server verification steps. Also, 'no admin required' is not enforced.

## Acceptance Criteria

- [ ] AC-6.1: setup command has --port, --no-interactive, --force options
- [ ] AC-6.2: Step 1: Check prerequisites
- [ ] AC-6.3: Step 2: Find available port (auto-discover if default in use)
- [ ] AC-6.4: Step 3: Create per-user directories (config, logs)
- [ ] AC-6.5: Step 5: Configure Claude Code CLI
- [ ] AC-6.6: Step 6: Verify server connectivity
- [ ] AC-6.7: No admin required

## Context

[Background, constraints - optional]
