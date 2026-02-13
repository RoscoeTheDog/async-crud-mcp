---
$schema: story-file-v5.1
id: '16'
title: Daemon infrastructure (paths, logging, shutdown, session, health)
type: feature
status: queued
parent: null
created_at: '2026-02-13T01:59:57.022734+00:00'
updated_at: '2026-02-13T01:59:57.022734+00:00'
depends_on:
- 2
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

# Story 16: Daemon infrastructure (paths, logging, shutdown, session, health)

## Description

Implement daemon support modules: paths, logging_setup, graceful_shutdown, session_detector, config_init, config_watcher, health, installer, bootstrap_daemon.

## Acceptance Criteria

- [ ] AC-16.1: paths.py: Cross-platform config/logs/data dir resolution
- [ ] AC-16.2: logging_setup.py: loguru with enqueue=True, rotation, fallback chain
- [ ] AC-16.3: graceful_shutdown.py: await logger.complete() in finally
- [ ] AC-16.4: session_detector.py: Cross-platform session detection
- [ ] AC-16.5: config_init.py: Config generation, find_available_port()
- [ ] AC-16.6: config_watcher.py: Debounced config reads, last-known-good fallback
- [ ] AC-16.7: health.py: Health check, port listening detection
- [ ] AC-16.8: installer.py: ABC factory installer pattern
- [ ] AC-16.9: bootstrap_daemon.py: Session-aware bootstrap loop

## Context

[Background, constraints - optional]
