---
$schema: story-file-v5.1
id: '3'
title: Fix bootstrap_daemon configure_logging retention and add console enqueue
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:02:09.764039+00:00'
updated_at: '2026-02-17T07:02:09.764039+00:00'
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

# Story 3: Fix bootstrap_daemon configure_logging retention and add console enqueue

## Description

configure_logging() in bootstrap_daemon.py uses retention=3 (int, 3 files) instead of '7 days' string retention per spec. The console handler is also missing enqueue=True for async safety (ADR-005). File handler is missing gz compression.

**Drift Source**: BOOTSTRAP.template.md + PYTHON_STACK.template.md (Logging Standard)
**Max Severity**: minor
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-3.1: configure_logging() file handler uses retention='7 days' string format
- [ ] AC-3.2: configure_logging() console handler has enqueue=True for async safety
- [ ] AC-3.3: configure_logging() adds gz compression to file handler

## Context

[Background, constraints - optional]
