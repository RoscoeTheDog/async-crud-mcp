---
$schema: story-file-v5.1
id: '2'
title: Add HTTP /health endpoint to server.py
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:01:51.445126+00:00'
updated_at: '2026-02-17T07:01:51.445126+00:00'
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

# Story 2: Add HTTP /health endpoint to server.py

## Description

The spec requires a proper HTTP /health endpoint returning status, version, and uptime. Currently server.py only exposes a health_tool() as an MCP tool. A dedicated HTTP /health route should be added so external health monitors and installers can check server health without MCP client setup.

**Drift Source**: SERVICE.template.md + INTEGRATION.template.md (Health Check Endpoints)
**Max Severity**: major
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-2.1: HTTP GET /health endpoint returns JSON with status, version, uptime fields
- [ ] AC-2.2: Health endpoint is accessible via plain HTTP (not MCP protocol)
- [ ] AC-2.3: Returns 200 OK for healthy status, 503 for unhealthy
- [ ] AC-2.4: scripts/test_server.py can check the HTTP /health endpoint

## Context

[Background, constraints - optional]
