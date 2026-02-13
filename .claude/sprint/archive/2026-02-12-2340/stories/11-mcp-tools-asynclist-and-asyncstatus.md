---
$schema: story-file-v5.1
id: '11'
title: 'MCP tools: async_list and async_status'
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:22.725227+00:00'
updated_at: '2026-02-13T01:59:22.725227+00:00'
depends_on:
- 8
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

# Story 11: MCP tools: async_list and async_status

## Description

Implement async_list() for directory listing and async_status() for server/file status.

## Acceptance Criteria

- [ ] AC-11.1: async_list: glob pattern filtering, recursive option
- [ ] AC-11.2: async_list: include_hashes attaches cached hashes
- [ ] AC-11.3: async_list: no lock acquisition
- [ ] AC-11.4: async_status: global status (version, uptime, locks, queue)
- [ ] AC-11.5: async_status: per-file status

## Context

[Background, constraints - optional]
