---
$schema: story-file-v5.1
id: '8'
title: 'Core MCP tools: async_read and async_write'
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:20.929232+00:00'
updated_at: '2026-02-13T01:59:20.929232+00:00'
depends_on:
- 3
- 4
- 5
- 6
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

# Story 8: Core MCP tools: async_read and async_write

## Description

Implement async_read() and async_write() MCP tools with lock coordination, hash computation, and error handling.

## Acceptance Criteria

- [ ] AC-8.1: async_read: path validation, shared read lock, content+hash response
- [ ] AC-8.2: async_read: offset/limit support
- [ ] AC-8.3: async_write: fails if file exists
- [ ] AC-8.4: async_write: exclusive write lock with FIFO
- [ ] AC-8.5: async_write: atomic write via file_io layer
- [ ] AC-8.6: async_write: create_dirs support

## Context

[Background, constraints - optional]
