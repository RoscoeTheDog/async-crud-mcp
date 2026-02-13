---
$schema: story-file-v5.1
id: '8'
title: Add port validation and from_file class method to config
type: feature
status: queued
parent: null
created_at: '2026-02-13T07:54:06.826823+00:00'
updated_at: '2026-02-13T07:54:06.826823+00:00'
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

# Story 8: Add port validation and from_file class method to config

## Description

The config.py is missing several spec requirements: (1) Port validation: ge=1024, le=65535 or null - currently no port range validation; (2) Host validation: non-empty string; (3) Settings.from_file() class method for per-user config loading - currently only get_settings() function; (4) _strip_comment_fields() function; (5) _force_reload option on get_settings(); (6) session_poll_seconds is not in DaemonConfig defaults from spec (it exists but should be verified).

## Acceptance Criteria

- [ ] AC-8.1: Port validation: ge=1024, le=65535 or null
- [ ] AC-8.2: Host validation: non-empty string
- [ ] AC-8.3: Settings.from_file(config_path) class method
- [ ] AC-8.4: get_settings() singleton accessor with _force_reload option
- [ ] AC-8.5: _strip_comment_fields() for _/$-prefixed comment removal

## Context

[Background, constraints - optional]
