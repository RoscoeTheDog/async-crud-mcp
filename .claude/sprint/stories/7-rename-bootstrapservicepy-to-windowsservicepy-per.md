---
$schema: story-file-v5.1
id: '7'
title: Rename bootstrap_service.py to windows_service.py per ADR-014
type: feature
status: queued
parent: null
created_at: '2026-02-17T07:03:27.318007+00:00'
updated_at: '2026-02-17T07:03:27.318007+00:00'
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

# Story 7: Rename bootstrap_service.py to windows_service.py per ADR-014

## Description

The spec and ADR-014 require the Windows pywin32 service file to be named windows_service.py, but the project uses bootstrap_service.py. Rename the file and update all imports, references, docstrings, and documentation that reference the old name. Files affected: daemon/installer.py (2 imports), daemon/windows/__init__.py (import + docstring), daemon/windows/dispatcher.py (comment), docs/PRD.md (2 references).

**Drift Source**: SERVICE.template.md + ADR-014
**Max Severity**: major
**Classification**: drifted

## Acceptance Criteria

- [ ] AC-7.1: File renamed from src/async_crud_mcp/daemon/windows/bootstrap_service.py to windows_service.py
- [ ] AC-7.2: Import in daemon/installer.py updated: from .windows.windows_service import install_service
- [ ] AC-7.3: Import in daemon/installer.py updated: from .windows.windows_service import uninstall_service
- [ ] AC-7.4: Import in daemon/windows/__init__.py updated: from .windows_service import (...)
- [ ] AC-7.5: Docstring/comment references in __init__.py, dispatcher.py, and docs/PRD.md updated
- [ ] AC-7.6: No remaining references to bootstrap_service in source code (excluding archives/sprint tmp)

## Context

[Background, constraints - optional]
