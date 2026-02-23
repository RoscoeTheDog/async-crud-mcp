# PRD Drift Report: async-crud-mcp Sprint Implementation

**Generated**: 2026-02-23 | **Updated**: 2026-02-23 (downstream audit + verification pass + sprint-era scope correction)
**Purpose**: Document drift between PRD spec and actual implementation across sprint cycles (Sprints 1-4)
**Use Case**: Improve CREATE_SPRINT accuracy for future projects
**Scope**: Sprint-era analysis anchored to `6e8d330` (Sprint 4 completion). Post-sprint manual work documented separately.

---

## Verification Notes (added during accuracy review)

This report was generated in a long session that hit auto-compaction. A verification pass corrected the following errors introduced by context loss:

| Claim | Original (Wrong) | Corrected | Source |
|-------|-------------------|-----------|--------|
| Sprint count | "4 sprints, 4 archives" | 4 sprints, 6 archives (duplicates) | `ls .claude/sprint/archive/` |
| Sprint 3 scope | "15+ new stories" | Reused Sprint 2's 15 stories + 1 new story file | `diff` of story dirs |
| Sprint 1 Gate 3 | "405/412 tests passed" | 291 passed, 9 failed (per checkpoint.json); SUMMARY says 300/0/4 | `checkpoint.json` phase_3_state |
| Sprint 1 Gate 4 | "5/15 stories validated, 9 blocked, 1 failed" | 7/20 stories validated, all passed. 13 never validated. | `validation/` directory listing |
| Total fix stories | "~37 (1.85x ratio)" | 22 unique (15 S2 + 7 S4; S3 reused S2) = 1.1x ratio | Archive analysis |
| "87 deliverables" timing | "before Sprint 2 creation" | Cited in Sprint 3 init commit (`9f18ad1`) | `git log` |
| Config sections | "7 extra sections" | 8 config model classes (4 PRD + 4 extra) | `grep class.*Config.*BaseModel config.py` |
| SUMMARY.md test count | Taken at face value (300/0) | Contradicted by checkpoint (291/9) | `checkpoint.json` |
| BUG-01 attribution | "BUG-01 (Health endpoint)" | BUG-01 = Windows Service Error 1053 / ReportServiceStatus. Health comes from PRD 11.2 | Story file review |
| Cat 1 flag names (S2-3,4,5,7) | Fabricated flags (--yes, --service-name, --format, --editor, --no-service) | Replaced with actual flags from story ACs | Story file AC verification |
| Appendix B scope | Analyzed HEAD state (`b046b65`), mixing sprint-era and post-sprint | Refocused on Sprint 4 completion (`6e8d330`); post-sprint separated to B.7 | `git show 6e8d330:` verification |
| B.2 tool behavior | "Content scanner runs post-read" (presented as sprint-era) | At Sprint 4: all 11 tools matched PRD exactly, no behavioral extensions | `git show 6e8d330:server.py` |
| B.3 ContentionResponse | Listed 5 extra fields | At Sprint 4: no extra fields, matched PRD exactly | `git show 6e8d330:models/responses.py` |
| B.3 error codes | "Implementation adds 7 more" | At Sprint 4: exactly 14 codes matching PRD 1:1. 7 added post-sprint | `git show 6e8d330:models/responses.py` |
| B.4 config sections | "Actual has 8" | At Sprint 4: exactly 4 sections matching PRD. 4 added post-sprint | `git show 6e8d330:config.py` |
| B.4.2 max_file_size_bytes | "Actual: 256MB (25x larger)" | At Sprint 4: 10MB matching PRD. Changed to 256MB post-sprint | `git show 6e8d330:config.py` |
| B.5 anyio | "Added for async compat" (implied Sprint 4) | Added post-sprint by `18c594d` | `git log -S anyio -- pyproject.toml` |
| C.3 anyio | Tagged "Sprint 4" | Moved to post-sprint (C.4) | Same verification |
| B.7 commit count | "15 commits" starting from `fbc2c8e` | 29 commits starting from `6e8d330` (includes 13 earlier post-sprint commits) | `git log --oneline 6e8d330..b046b65` |

**Note on SUMMARY.md vs checkpoint.json discrepancy**: The SUMMARY.md claims "300 passed, 0 failed, 4 skipped" while the checkpoint's `phase_3_state` shows `"passed": 291, "failed": 9, "total": 300`. The SUMMARY was likely generated at a different time or from a different test run than the checkpoint. The checkpoint data is more authoritative as it's machine-generated during orchestration.

---

## Executive Summary

The async-crud-mcp project went through **4 sprint cycles** to reach alignment with the PRD and daemon-service template:

| Sprint | Archive(s) | Stories | Deferred | Purpose | Gap Source |
|--------|------------|---------|----------|---------|------------|
| Sprint 1 | `20260212_233441` + `2026-02-12-2340` (duplicates) | 23 | 3 (tests) | Original implementation | PRD -> stories |
| Sprint 2 | `20260213-164721` + `20260213-164953` (duplicates, `164810` is empty) | 15 | 0 | Drift correction #1 | Spec comparison |
| Sprint 3 | `2026-02-16-2040` | 15 (same stories as Sprint 2, re-validated) | 0 | Re-validation of Sprint 2 fixes | 87-deliverable gap analysis |
| Sprint 4 | current `.claude/sprint/` | 7 | 0 | Final patches | Runtime testing |

**Archive note**: 6 archive directories exist due to duplicate archiving. Sprint 1 has 2 copies, Sprint 2 has 3 copies (one empty). Sprint 3 reused Sprint 2's 15 story definitions and re-ran orchestration/validation, adding 1 new story file (`11-fix-installer-service-install-and-add-post-install.md`).

**Key metric**: Sprint 2 created 15 remediation stories, Sprint 3 re-validated and fixed remaining issues from those same stories, Sprint 4 added 7 new stories. Total unique remediation stories: **22** (15 from Sprint 2 + 7 from Sprint 4). **Drift ratio: 1.1x** (22 fix stories / 20 original stories).

**Sprint 1 validation was misleading**: Gate 3 ran tests showing 291 passed, 9 failed per checkpoint data (SUMMARY.md rounds to "300 passed, 0 failed" which is inaccurate). Gate 4 validated only **7 of 20** completed stories (stories 1, 4, 7, 10, 12, 15, 16 - all PASSED or PASSED_WITH_NOTES). The remaining **13 stories were never semantically validated** in Sprint 1. The checkpoint's `phase_4_state` only records story 9 in `validation_findings`. This lack of validation coverage is the primary reason spec drift went undetected.

**Test count progression** (verified from git commit messages):
- Sprint 1: 300 passed, 0 failed, 4 skipped (per SUMMARY; checkpoint shows 291/9/300)
- Sprint 2: 405 passed, 0 failed, 7 skipped
- Sprint 3: 404 passed, 0 failed, 8 skipped
- Sprint 4: 423 passed, 0 failed, 7 skipped

**Code-level compliance at Sprint 4 completion** (`6e8d330`): All 11 PRD-specified tool signatures match exactly. All 14 PRD error codes match 1:1. All 6 PRD-specified core components are fully compliant. Config had exactly 4 sections matching PRD, with `max_file_size_bytes` at 10MB (matching PRD). 11 of 11 PRD dependencies present. Remaining structural drift is limited to: flat daemon/windows files (PRD expects nested directory), CLI `_cmd` suffix (intentional), and relaxed Python version (3.10 vs 3.12).

**Post-sprint evolution** (outside sprint scope): After Sprint 4, **29 additional commits** added substantial features beyond the PRD: shell execution (3 tools), content scanning/redaction, audit logging, process containment, and per-project configuration (3 tools). At HEAD (`b046b65`), the implementation has 18 MCP tools, 12 core modules, and 8 config sections vs the PRD's 11/6/4. These represent organic feature growth through manual incremental work, not sprint-orchestrated drift.

---

## CREATE_SPRINT Gap Analysis (for agent consumption)

> **Context for the consuming agent**: This section answers the question "what types of spec details did CREATE_SPRINT fail to capture as acceptance criteria?" It is based solely on the **sprint-era** execution (Sprints 1-4). Everything in Appendix B.7 (post-sprint commits) is **out of scope** - those were manual incremental changes made without sprint orchestration and are NOT examples of CREATE_SPRINT failures.
>
> **Timeline boundary**: Sprint 1 created 23 stories from the PRD. Sprint 2 created 15 remediation stories. Sprint 4 created 7 more. The drift this report analyzes is between Sprint 1's stories (what was intended) and what the subagents actually built (what resulted), which Sprint 2/4 then had to fix.

### What category of missed detail caused the most drift?

**Answer: Implicit constraints (Category 3)** with significant contribution from **specific numeric/flag values (Category 1)**. Cross-file contracts (Category 2) were NOT a significant source of drift in this project.

### Category Breakdown With Evidence

#### Category 1: Specific Values (flags, options, exit codes) - 40% of remediation stories

CREATE_SPRINT generated ACs like `bootstrap: install/uninstall/start/stop/status/list` without enumerating the specific CLI flags each command requires. The PRD and templates specified these flags, but CREATE_SPRINT collapsed them into single-line ACs.

**What was in the PRD/templates but NOT in Sprint 1 ACs:**

| Type | Examples From Actual Stories | Stories That Fixed It |
|------|----------------------------|----------------------|
| CLI flags | `--force`, `--use-task-scheduler`, `--username`, `--json`, `--follow`, `--lines` | S2: 2,3,4,5,6,7 (6 stories) |
| Exit codes | Exit code 48 on EADDRINUSE | S2: 9 |
| Port defaults | DEFAULT_PORT alignment, port validation `ge=1024, le=65535` | S2: 8, 12 |
| Menu options | 4-option menu (Install/Reinstall/Uninstall/Quit) vs implemented 3-option | S4: 4 |
| Script CLI args | `--port`, `--skip-logs`, `--log-age` on test_server.py | S2: 13 |

**The gap**: CREATE_SPRINT read the PRD's `bootstrap install` command description but generated `AC-19.1: bootstrap: install/uninstall/start/stop/status/list` - a single AC covering 6 commands. The PRD's template specified each command's flags individually. The subagent implemented the command skeletons but with default/minimal options because the AC didn't tell it what flags were required.

**Fix for CREATE_SPRINT**: When a PRD section describes a CLI command with specific flags, each flag MUST become its own AC or sub-AC. Never collapse multiple commands into one AC line.

#### Category 2: Cross-file contracts - NOT a significant drift source

At Sprint 4 completion, all inter-module contracts were correct:
- Lock manager was correctly called by all tool implementations
- File I/O's `atomic_write` was correctly used by persistence layer
- Path validator was correctly integrated into all tool entry points
- Hash registry was correctly updated by file watcher events

**Why this wasn't a problem**: The PRD specified each module's interface clearly (Section 4), and Sprint 1's stories decomposed them into individual modules. The subagents implemented the interfaces correctly. The drift was not in HOW modules connected but in WHAT DETAILS each module exposed (missing flags, missing config options).

#### Category 3: Implicit constraints (templates, ADRs, guardrails) - 35% of remediation stories

The PRD referenced 8 template files and 20+ ADRs, but CREATE_SPRINT did not expand these references into explicit ACs. The subagents never saw the template content - they only saw the high-level story description.

**What was implicit but NOT stated in Sprint 1 ACs:**

| Type | Implicit Constraint | Where It Was Specified | Stories That Fixed It |
|------|---------------------|----------------------|----------------------|
| Template pattern | `Settings.from_file()` class method | CONFIG.template.md | S2: 8 |
| Template pattern | `_strip_comment_fields()` function | CONFIG.template.md | S2: 8 |
| Template pattern | `session_poll_seconds` in generate_default_config | CONFIG.template.md | S2: 12 |
| ADR naming | APP_NAME must use single constant, not variants | ADR-009 | S2: 10 |
| ADR naming | File must be `windows_service.py`, not `bootstrap_service.py` | ADR-014 | S4: 7 |
| ADR behavior | Port conflict must exit with code 48 | ADR-012 | S2: 9 |
| Guardrail | pywin32 DLL copying for Windows service | PRD Section 13 (GAP-5) | S2: 11 |
| Guardrail | HTTP `/health` endpoint (not just MCP tool) | PRD Section 11.2 | S4: 2 |
| Template layout | `daemon/windows/` nested subdirectory | PRD Section 2.3 file tree | NEVER FIXED (still flat) |
| Template layout | pyproject.toml src layout configuration | PYTHON_STACK.template.md | S2: 1 |
| Build config | `requires-python >= 3.10` (not 3.12) | PYPROJECT.template.md | S4: 6 |
| Dependency | `mcp>=1.0.0` in dependencies | PRD Section 6 (implied) | S4: 6 |

**The gap**: CREATE_SPRINT treated template references as informational context rather than extracting their specific requirements into ACs. When a PRD says "implement config per CONFIG.template.md", the subagent doesn't have the template - it only has the AC. If the AC says "implement config system" without specifying `from_file()`, `_strip_comment_fields()`, and `session_poll_seconds`, the subagent will create a working config system that doesn't match the template.

**Fix for CREATE_SPRINT**: When the PRD references a template file, CREATE_SPRINT MUST read that template and generate ACs for each specific pattern, method, naming convention, and structural requirement it contains. Template references are not documentation - they are requirements that need AC decomposition.

#### Category 4: Documentation/config (15% of remediation stories)

| Type | What Drifted | Stories |
|------|-------------|---------|
| README content | Missing CLI examples, architecture overview | S2: 14, S4: 5 |
| .gitignore | Missing `.ruff_cache` pattern | S2: 15 |
| pyproject.toml | requires-python, missing dependency | S4: 6 |

**The gap**: Low-priority items that CREATE_SPRINT deprioritized or collapsed into other stories. Not a systematic failure - just normal task prioritization.

### Summary For CREATE_SPRINT

```
DRIFT CAUSE DISTRIBUTION (this project):
  Category 3 (Implicit constraints):  35%  ← PRIMARY PROBLEM
  Category 1 (Specific values/flags):  40%  ← SECONDARY PROBLEM
  Category 4 (Docs/config):            15%  ← Minor
  Category 2 (Cross-file contracts):    0%  ← Not a problem here

  Note: Categories 1 and 3 overlap. Many "specific values" (flags, exit
  codes) were implicit constraints from templates/ADRs. The root cause
  is the same: CREATE_SPRINT didn't decompose template/ADR references
  into granular ACs with specific values.

WHAT CREATE_SPRINT SHOULD DO DIFFERENTLY:
  1. RESOLVE template references into explicit ACs (don't pass-through)
  2. ONE AC per CLI command per flag set (don't collapse 6 commands into 1 AC)
  3. EXTRACT ADR/guardrail requirements into tagged ACs per affected story
  4. ENUMERATE specific values (flag names, exit codes, port ranges, file names)
  5. SPLIT large infrastructure stories (>5 ACs) into per-component stories

WHAT WAS NOT A PROBLEM (do not over-correct):
  - Module interfaces and cross-file contracts worked correctly
  - Core algorithm implementations (locking, hashing, diffing) matched PRD
  - Error code definitions matched PRD exactly
  - Config value defaults matched PRD exactly
  - Dependency versions were correct
  - The subagents built working code - it just didn't match template specifics
```

### What This Report Does NOT Cover

This report analyzes a **greenfield project** (new repo built from a PRD). The findings may apply differently to **brownfield projects** (existing codebases with established patterns). Specifically:

- **Brownfield projects** have existing cross-file contracts that CREATE_SPRINT must understand and preserve. Category 2 drift may be more significant in brownfield scenarios.
- **Brownfield projects** have existing config values, naming conventions, and architectural patterns that are implicit constraints not in any PRD. These would fall under Category 3 but require codebase analysis rather than template resolution.
- **This project's PRD was comprehensive** (1586 lines, 13 sections, 8 templates, 20+ ADRs). Projects with less detailed PRDs may have different drift patterns.

---

## Root Cause Analysis

### ROOT CAUSE 1: Story Granularity Was Too Coarse (CRITICAL)

Sprint 1 stories were written as high-level feature summaries, not detailed implementation specs. This is the single biggest cause of drift.

**Example - Story 19 (CLI commands)**:
```
Acceptance Criteria:
- AC-19.1: bootstrap: install/uninstall/start/stop/status/list
- AC-19.2: daemon: start/stop/restart/status/logs
- AC-19.3: config: init/show/edit/validate
- AC-19.4: install: quick-install and uninstall
- AC-19.5: setup: Per-user setup wizard (no admin)
```

What was missing from these ACs that Sprint 2 had to add:
- Each command's specific `--flags` and options (e.g., `--force`, `--use-task-scheduler`, `--username`, `--json`)
- Setup wizard multi-step flow with specific step ordering
- `quick-install` and `uninstall` as top-level commands (not subgroups)
- `version` command showing `__version__`
- Status commands requiring `--username`, `--all`, `--json` options

**Impact**: 6 of Sprint 2's 15 stories (40%) were exclusively about adding missing CLI options and command structure that the original story didn't specify.

### ROOT CAUSE 2: Template References Were Not Resolved Into ACs

The PRD extensively references the daemon-service template (8 template files, 20+ snippets), but Sprint 1 stories didn't expand those references into concrete acceptance criteria.

**Example - Story 20 (Installation scripts)**:
```
AC-20.3: installer.py: stdlib-only, install/uninstall/menu
```

The daemon-service `INSTALLER.template.md` specifies:
- 4-option menu (Install/Reinstall/Uninstall/Quit) - not Install/Uninstall/Test/Exit
- Privilege elevation check before install
- Pre-flight checks (Python version, disk space)
- `uv venv --managed-python` for stable venvs
- pywin32 DLL copying (5 specific files)
- Post-install steps (setup wizard, server test)
- Installer log file for debugging
- Exit codes for each failure mode

None of these were in the AC. The subagent implemented a basic installer that worked but didn't match the template spec.

**Impact**: Sprint 2 story 11 (Fix installer) was rated 4pt/high-risk. Sprint 3 stories 6-7 further fixed the setup wizard and install commands. Sprint 4 story 4 further aligned the menu options. One installer feature needed fixes across 3 separate sprints.

### ROOT CAUSE 3: ADR Requirements Were Invisible To Subagents

The PRD's Section 13 ("Implementation Guardrails") documents 13 critical ADR requirements. Sprint 1 stories didn't reference specific ADRs in their ACs.

**Specific ADRs that drifted**:
- **ADR-009** (APP_NAME naming): paths.py used inconsistent APP_NAME import -> Sprint 2 story 10
- **ADR-012** (Port conflict detection): No exit code 48 on EADDRINUSE -> Sprint 2 story 9
- **ADR-014** (File naming): File named `bootstrap_service.py` instead of `windows_service.py` -> Sprint 4 story 7
- **PRD Section 11.2** (Health endpoint): Missing HTTP /health endpoint (only MCP tool existed) -> Sprint 4 story 2. *(Note: this was previously mis-attributed to BUG-01, which is actually about Windows Service Error 1053 / ReportServiceStatus)*

### ROOT CAUSE 4: "Works" != "Matches Spec" - Validation Gap

The sprint's Gate 3 (testing) and Gate 4 (validation) couldn't detect spec compliance drift:

- **Gate 3**: Sprint 1 tests showed 291 passed/9 failed per checkpoint (SUMMARY.md overstates as "300 passed, 0 failed"). Tests were written BY the same subagents who implemented the features, validating the implementation that existed, not the implementation the PRD specified.
- **Gate 4**: Only **7 of 20** completed stories received Phase A semantic validation (stories 1, 4, 7, 10, 12, 15, 16). The remaining **13 stories were never validated**. The checkpoint's `phase_4_state` has minimal data (only story 9 in `validation_findings`), suggesting the validation pipeline had incomplete coverage or was partially overridden.
- **Gate 5**: Sprint 1 SUMMARY shows no remediation stories were generated despite the validation gaps, because the stories that WERE validated all passed - the drift was in the 13 unvalidated stories.

---

## Drift Taxonomy

### Category 1: CLI Option/Flag Omissions (40% of drift stories)

| Sprint | Story | What Was Missing |
|--------|-------|-----------------|
| S2 | 2 | setup as direct command, quick-install/uninstall as top-level, version command |
| S2 | 3 | Bootstrap CLI: --force, --use-task-scheduler (install); --username, --force (uninstall); --username (start/stop); --username, --json (status) |
| S2 | 4 | Daemon CLI: --follow, --lines, --username, --user (logs); --username, --all, --json (status); config mutation for start/stop/restart |
| S2 | 5 | Config CLI: --port, --no-interactive, --username (init); --username, --json (show); pydantic validation |
| S2 | 6 | Setup wizard: multi-step flow, step ordering, skip logic |
| S2 | 7 | Install CLI: --force, --port, --no-start (quick-install); --keep-config/--remove-config, --keep-logs/--remove-logs, --force (uninstall) |

**Characteristic**: The subagent created the command skeleton but with default/minimal options. The template specified detailed flags per command.

**Pattern for CREATE_SPRINT improvement**: When a story says "implement CLI command X with operations A/B/C", each operation should be a separate AC with its specific flags enumerated. Don't let "bootstrap: install/uninstall/start/stop/status/list" be one AC - that's 6 commands each needing their own flag set.

### Category 2: Template/ADR Non-Compliance (25% of drift stories)

| Sprint | Story | Template/ADR Violated |
|--------|-------|----------------------|
| S2 | 1 | pyproject.toml build layout (PYTHON_STACK.template.md) |
| S2 | 8 | Config port validation + from_file (CONFIG.template.md) |
| S2 | 10 | APP_NAME import pattern (ADR-009) |
| S2 | 12 | config_init DEFAULT_PORT + session_poll_seconds (CONFIG.template.md) |
| S4 | 7 | File naming: bootstrap_service.py -> windows_service.py (ADR-014) |

**Characteristic**: PRD Section 2.1 listed 8 template files and 20+ snippets to copy. The subagents created new files from scratch rather than adapting the template snippets. Template patterns (naming, config structure, port allocation) were reimplemented differently.

**Pattern for CREATE_SPRINT improvement**: For template-derived projects, each template should generate explicit ACs for its specific requirements. A "copy snippet X to path Y" story should validate the snippet's critical patterns are preserved, not just that a file exists at the path.

### Category 3: Infrastructure Feature Gaps (20% of drift stories)

| Sprint | Story | What Was Missing |
|--------|-------|-----------------|
| S2 | 9 | Port pre-flight exit code 48, security logging for non-localhost |
| S2 | 11 | installer.py: venv CLI bootstrap install (not service_installer.bat), post-install steps |
| S2 | 13 | test_server.py: --port, --skip-logs, --log-age options |
| S4 | 1 | ProgramData fallback path for daemon logs |
| S4 | 2 | HTTP /health endpoint (only had MCP tool, not HTTP route) |
| S4 | 3 | bootstrap_daemon logging: retention + console enqueue |

**Characteristic**: The PRD's Section 13 "Implementation Guardrails" contains 13 critical requirements from production bugs. These were documented but not tracked as individual ACs within stories.

**Pattern for CREATE_SPRINT improvement**: Implementation guardrails should be cross-referenced into the stories that implement the affected components. E.g., Story 17 (Windows service) should include ACs for BUG-01 (ReportServiceStatus), BUG-02 (no asyncio.run), BUG-07 (try/except SvcDoRun).

### Category 4: Naming/Documentation/Config (15% of drift stories)

| Sprint | Story | What Was Missing |
|--------|-------|-----------------|
| S2 | 14 | README: comprehensive documentation |
| S2 | 15 | .ruff_cache in .gitignore |
| S4 | 5 | README: CLI usage examples, architecture overview |
| S4 | 6 | pyproject.toml: requires-python alignment, missing mcp dependency |

**Characteristic**: Low-priority but persistent. Documentation stories kept appearing because the initial README was minimal and pyproject.toml dependencies drifted.

---

## Cross-Sprint Drift Recurrence

Some features required fixes across multiple sprints, indicating the fix was incomplete or the spec was underspecified:

| Feature | S1 Story | S2 Story | S3 Story* | S4 Story | Sprint Touches | Story Count |
|---------|----------|----------|-----------|----------|----------------|-------------|
| installer.py | 20 | 11 | 11 | 4 | 4 (3 unique) | 4 |
| CLI commands | 19 | 2-7 | 2-7 | - | 3 (2 unique) | 13 |
| pyproject.toml | 1 | 1 | 1 | 6 | 4 (3 unique) | 4 |
| README | - | 14 | 14 | 5 | 3 (2 unique) | 3 |
| test_server.py | 20 | 13 | 13 | - | 3 (2 unique) | 3 |
| server.py | 13 | 9 | 9 | 2 | 4 (3 unique) | 4 |
| config | 2 | 8, 12 | 8, 12 | - | 3 (2 unique) | 5 |

*\*S3 reused S2's story files; "unique" counts exclude S3 as a distinct implementation sprint.*

**installer.py** was the worst offender, appearing in all 4 sprint cycles (3 unique). **CLI commands** had the highest story count (13 individual stories across S1-S3).

---

## Quantitative Analysis

### Gap Analysis (cited in Sprint 3 init commit)
- **87 deliverables** scanned against daemon-service template
- **70 done** (80.5%) - functionally complete
- **17 need modification** (19.5%) - spec non-compliant
- This 20% drift rate generated 15 remediation stories (Sprint 2)
- **Note**: The "87 deliverables" figure appears in Sprint 3's init commit (`9f18ad1`), not in Sprint 2's init. It likely comes from the gap analysis session that created Sprint 2, but was only recorded in the Sprint 3 commit message.

### Sprint 1 Validation Accuracy
- Gate 3 tests: **291 passed, 9 failed** out of 300 (per checkpoint.json). SUMMARY.md claims "300 passed, 0 failed" which is contradicted by the checkpoint data.
- Gate 4 validation: Only **7 of 20** completed stories received Phase A semantic validation (stories 1, 4, 7, 10, 12, 15, 16). All 7 passed.
- **13 of 20** completed stories were **never semantically validated** in Sprint 1.
- The checkpoint's `phase_4_state.validation_findings` only contains story 9, suggesting the validation pipeline had partial coverage.

### Token/Cost Impact
- Sprint 1: 23 stories, 20 completed, ~24K lines of code
- Sprint 2: 15 alignment stories (new), code changes
- Sprint 3: Same 15 stories re-orchestrated, 1 new story file added for installer fix
- Sprint 4: 7 new alignment stories, ~2K lines changed
- **Unique remediation stories**: 22 (15 Sprint 2 + 7 Sprint 4; Sprint 3 reused Sprint 2 stories)

---

## Recommendations for CREATE_SPRINT Improvement

### R1: Expand Template References Into Explicit ACs
When the PRD references external templates, CREATE_SPRINT should:
1. Read each referenced template
2. Extract its specific requirements (flags, patterns, naming conventions)
3. Generate ACs that reference the template requirement by ID/name
4. Never leave "implement per template" as an AC - that's a placeholder, not a spec

### R2: One AC Per Command/Flag, Not Per Feature Group
Instead of: `AC-19.1: bootstrap: install/uninstall/start/stop/status/list`
Generate:
- `AC-19.1a: bootstrap install --force --use-task-scheduler`
- `AC-19.1b: bootstrap uninstall --username --force`
- `AC-19.1c: bootstrap status --username --json`
- etc.

### R3: Cross-Reference Implementation Guardrails Into Stories
For each guardrail/ADR in the PRD, CREATE_SPRINT should:
1. Identify which story implements the affected component
2. Add specific ACs for each guardrail requirement
3. Tag the AC with the ADR/BUG number for traceability

### R4: Generate "Negative" ACs for Known Patterns
Add ACs that explicitly test for common drift patterns:
- "File MUST be named X, not Y" (naming drift)
- "Command MUST have --flag-name option" (flag omission)
- "Exit code MUST be N on error condition X" (error handling)
- "Menu MUST show options in order: A, B, C, D" (UI sequence)

### R5: Split Infrastructure Stories by Template Source
Instead of: "Story 20: Installation scripts" (8 ACs for 7 different scripts)
Generate: One story per script with detailed ACs from the template:
- "Story 20a: installer.py with 4-option menu, privilege check, pywin32 DLL copy"
- "Story 20b: test_server.py with --port, --skip-logs, --log-age"
- etc.

### R6: Improve Validation to Detect Spec Compliance
Gate 4 validation should:
1. Compare each AC against the actual implementation (not just test results)
2. Not be overrideable by Gate 3 test results for "blocked" stories
3. Use the original template specs as validation reference, not just story ACs

### R7: Include "Spec Checksum" in Stories
Each story should include a hash/list of the specific PRD sections and template sections it covers. During validation, the validator can verify coverage against these sections rather than relying solely on AC checks.

---

## Session Index

### Key Sessions Analyzed

| Session ID | Date | Size | Role |
|------------|------|------|------|
| `5e1dc115` | Feb 12-13 | 2.9MB | Sprint creation + PRD authoring |
| `e146801f` | Feb 13 | 895KB | Sprint 1 CREATE_SPRINT |
| `e9f12db2` | Feb 13-14 | 8.6MB | Main orchestrator (Sprint 1 exec + Sprint 2 creation) |
| `787a542f` | Feb 14 | 2.9MB | Sprint 2 ORCHESTRATE |
| `fe384fb4` | Feb 13 | 4.3MB | Sprint 1 ORCHESTRATE (initial) |
| `3c8ee15b` | Feb 13 | 3.6MB | Large implementation session |
| `b609488a` | Feb 13 | 2.4MB | Large implementation session |

### Session Timeline (verified against git log dates)
1. **Feb 12 09:20**: Repo initialized (`2aa238f`)
2. **Feb 12 17:06-17:42**: PRD created in 3 commits (`e801980`, `c6dd6b7`, `50f1610`)
3. **Feb 12 18:03**: Sprint 1 initialized with 23 stories (`abbbcd5`)
4. **Feb 12 19:37-22:03**: Sprint 1 implemented in 4 batch commits (Batches 1-6)
5. **Feb 12 23:32-23:36**: Sprint 1 archived + merged (`f886731`, `9be3385`)
6. **Feb 12 23:57**: Sprint 2 initialized with 15 stories from gap analysis (`a50dffa`)
7. **Feb 13 02:53**: Sprint 2 completed (`232163c`) - 405/412 tests passed
8. **Feb 13 09:39**: Manual installer fix between sprints (`21bd1a8`)
9. **Feb 13 17:28**: Sprint 3 initialized - reused Sprint 2's 15 stories (`9f18ad1`)
10. **Feb 13 18:58**: Sprint 3 completed (`00fb266`) - 404/412 tests passed
11. **Feb 16 21:34**: Access control feature added (`673dfa2`) - between sprints
12. **Feb 16 23:06**: Sprint 4 initialized with 7 new stories (`44a96cb`)
13. **Feb 17 00:49**: Sprint 4 completed (`6e8d330`) - 423/430 tests passed
14. **Feb 18-21**: Post-sprint fixes: installer, CLI config, _pth file, shell extension
15. **Feb 20-21**: Shell tools added (`18c594d`), audit logging, security hardening
16. **Feb 21-23**: Content scanning, BIP-39 detection, redaction, max_file_size enforcement

---

## Appendix A: Full Drift Map

### Sprint 2 Stories (Drift Correction #1) - Detailed

| ID | Title | Classification | Severity | Drift Source |
|----|-------|---------------|----------|--------------|
| 1 | Align pyproject.toml with spec build layout | partial | minor | PYTHON_STACK.template.md |
| 2 | Complete CLI init with commands and subgroups | drifted | major | CLI_COMMANDS.template.md |
| 3 | Add missing options to bootstrap CLI | drifted | major | CLI_COMMANDS.template.md |
| 4 | Add missing options to daemon CLI | drifted | major | CLI_COMMANDS.template.md |
| 5 | Add missing options to config CLI | drifted | minor | CLI_COMMANDS.template.md |
| 6 | Align setup wizard with spec | drifted | major | CLI_COMMANDS.template.md |
| 7 | Align install commands with spec | drifted | minor | CLI_COMMANDS.template.md |
| 8 | Add port validation + from_file to config | missing | major | CONFIG.template.md |
| 9 | Add port pre-flight + security logging | missing | major | ADR-012, SERVICE.template.md |
| 10 | Align paths.py APP_NAME with ADR-009 | drifted | major | ADR-009 |
| 11 | Enhance installer.py with spec features | partial | high | INSTALLER.template.md |
| 12 | Add config_init DEFAULT_PORT alignment | partial | minor | CONFIG.template.md |
| 13 | Add test_server.py CLI args | missing | minor | INTEGRATION.template.md |
| 14 | Enhance README documentation | partial | minor | OVERVIEW.template.md |
| 15 | Add .ruff_cache to .gitignore | missing | trivial | PYTHON_STACK.template.md |

### Sprint 4 Stories (Drift Correction #3) - Detailed

| ID | Title | Classification | Severity | Drift Source |
|----|-------|---------------|----------|--------------|
| 1 | Add ProgramData fallback for daemon logs | missing | major | SERVICE.template.md |
| 2 | Add HTTP /health endpoint | drifted | major | SERVICE + INTEGRATION |
| 3 | Fix bootstrap_daemon logging retention | partial | minor | PYTHON_STACK.template.md |
| 4 | Align installer menu with spec options | drifted | minor | INSTALLER.template.md |
| 5 | Enhance README with CLI examples | partial | minor | OVERVIEW.template.md |
| 6 | Align pyproject.toml requires-python + deps | partial | minor | PYTHON_STACK.template.md |
| 7 | Rename bootstrap_service.py -> windows_service.py | drifted | major | ADR-014 |

---

## Appendix B: Downstream Code-Level Drift Analysis

> **Scope**: This appendix analyzes the codebase at **Sprint 4 completion** (`6e8d330`) unless otherwise noted. Post-sprint additions (commits after `6e8d330`) are documented separately in B.7.

### B.1 Structural Drift (Files & Directories)

Comparison of PRD Section 2.3 file tree vs actual `src/async_crud_mcp/` at Sprint 4 completion (`6e8d330`).

#### B.1.1 Tool Files at Sprint 4 Completion

At `6e8d330`, the `tools/` directory contained exactly **11 CRUD tool files** matching the PRD (async_read, async_write, async_update, async_delete, async_rename, async_append, async_list, async_status, async_batch_read, async_batch_write, async_batch_update). No extra tool files existed at this point.

The `server.py` registered **12 MCP tools** (11 CRUD + 1 health_tool). The `health_tool` was implemented inline in server.py (Sprint 1 Story 13), not as a separate file.

*Note: 3 additional tool files (async_exec.py, async_search.py, async_wait.py) and 3 config management tools were added post-sprint. See B.7.*

#### B.1.2 Core Modules at Sprint 4 Completion

PRD Section 4 specifies 6 core components. At `6e8d330`, exactly **6 core modules** existed:

| File | Purpose | PRD Section | Status |
|------|---------|-------------|--------|
| `core/lock_manager.py` | Per-file FIFO locks | 4.1 | Matches PRD |
| `core/file_io.py` | Atomic writes + hashing | 4.2 | Matches PRD |
| `core/diff_engine.py` | Diff computation | 4.3 | Matches PRD |
| `core/path_validator.py` | Path security | 4.4 | Matches PRD + access rules extension* |
| `core/file_watcher.py` | Filesystem monitoring | 4.6 | Matches PRD |
| `core/persistence.py` | State persistence | 4.5 | Matches PRD |

*\*Access rules (`access_rules: list[PathRule]`) were added by `673dfa2` between Sprint 3 and Sprint 4, outside sprint orchestration.*

*Note: 6 additional core modules (audit_logger, background_tasks, content_scanner, process_guard, shell_provider, shell_validator) were added post-sprint. See B.7.*

#### B.1.3 Directory Structure Drift

| PRD Expectation | Actual | Status |
|----------------|--------|--------|
| `daemon/windows/__init__.py` | Does not exist | **MISSING** |
| `daemon/windows/windows_service.py` | `daemon/windows_service.py` | **Wrong path** - flat instead of nested |
| `daemon/windows/dispatcher.py` | `daemon/dispatcher.py` | **Wrong path** - flat instead of nested |
| `daemon/windows/session_detector.py` | `daemon/session_detector.py` | **Wrong path** - flat instead of nested |
| `cli/bootstrap.py` | `cli/bootstrap_cmd.py` | **Renamed** with `_cmd` suffix |
| `cli/daemon.py` | `cli/daemon_cmd.py` | **Renamed** with `_cmd` suffix |
| `cli/install.py` | `cli/install_cmd.py` | **Renamed** with `_cmd` suffix |
| `cli/setup.py` | `cli/setup_cmd.py` | **Renamed** with `_cmd` suffix |
| `daemon/macos/launchd.plist` | Exists | OK |
| `daemon/macos/launchd_installer.sh` | Exists | OK |
| `daemon/linux/systemd.service` | Exists | OK |
| `daemon/linux/systemd_installer.sh` | Exists | OK |

**Key finding**: The `daemon/windows/` subdirectory was **never created**. Sprint 1 placed all Windows files flat under `daemon/`. Sprint 4 Story 7 renamed `bootstrap_service.py` to `windows_service.py` (per ADR-014) but did NOT move it into a `windows/` subdirectory. The `_cmd` suffix on CLI files was a Sprint 2 decision to avoid Python module naming conflicts with stdlib (`setup.py` conflicts with setuptools).

### B.2 MCP Tool Signature Drift (at Sprint 4 Completion)

#### B.2.1 PRD-Specified Tools (11 tools) - Parameter Comparison

At `6e8d330`, all 11 PRD-specified tools were implemented with parameters matching the PRD exactly. No behavioral extensions (content scanning, file size enforcement) existed yet - those were added post-sprint.

| Tool | PRD Spec | Sprint 4 State |
|------|----------|----------------|
| `async_read` | 4 params | Match. No deviations |
| `async_write` | 5 params | Match. No deviations |
| `async_update` | 7 params | Match. No deviations |
| `async_delete` | 4 params | Match. No deviations |
| `async_rename` | 7 params | Match. `cross_filesystem` bool in response (PRD mentions this) |
| `async_append` | 7 params | Match. No deviations |
| `async_list` | 4 params | Match. No deviations |
| `async_status` | 1 param | Match. No deviations |
| `async_batch_*` | per-PRD | Match. No deviations |

**Verdict**: At Sprint 4 completion, all 11 PRD tools had correct signatures with no behavioral drift.

#### B.2.2 Extra Tool: health_tool

The only extra tool at Sprint 4 completion was `health_tool` (no parameters), implemented inline in server.py since Sprint 1 (Story 13, AC-13.3). PRD Section 11.2 specifies an HTTP `/health` endpoint; the `health_tool` is an MCP-protocol duplicate of this. Sprint 4 Story 2 added the HTTP endpoint, so both now exist.

*Note: 6 additional tools (async_exec, async_wait, async_search, crud_activate_project, crud_get_config, crud_update_config) were added post-sprint. See B.7.*

### B.3 Response Model Drift (at Sprint 4 Completion)

#### B.3.1 ContentionResponse

At `6e8d330`, `ContentionResponse` matched the PRD Section 3.3 spec exactly. Fields: status, path, expected_hash, current_hash, message, diff, patches_applicable, conflicts, non_conflicting_patches, timestamp. **No extra fields.**

*Note: Post-sprint additions (error_code, redacted, redacted_pattern, redacted_hint, redactions) were added for content scanner integration. See B.7.*

#### B.3.2 Error Codes

At `6e8d330`, the `ErrorCode` enum contained exactly **14 values** matching PRD Section 7.1 one-to-one: FILE_NOT_FOUND, FILE_EXISTS, ACCESS_DENIED, PATH_OUTSIDE_BASE, LOCK_TIMEOUT, ENCODING_ERROR, INVALID_PATCH, CONTENT_OR_PATCHES_REQUIRED, FILE_TOO_LARGE, WRITE_ERROR, DELETE_ERROR, RENAME_ERROR, DIR_NOT_FOUND, SERVER_ERROR. **No drift.**

*Note: 7 additional error codes (COMMAND_DENIED, COMMAND_TIMEOUT, SHELL_DISABLED, SEARCH_DISABLED, TASK_NOT_FOUND, INVALID_PATTERN, VALIDATION_ERROR) and 6 extra response models were added post-sprint. See B.7.*

### B.4 Configuration Drift (at Sprint 4 Completion)

#### B.4.1 PRD Section 5 vs Config Sections at `6e8d330`

PRD defines 4 config sections. At Sprint 4 completion, exactly **4 config classes** existed (matching PRD):

| Section | PRD? | Key Settings | Match? |
|---------|------|-------------|--------|
| `daemon` | Yes | host, port, transport, log_level, config_poll_seconds, etc. | Yes |
| `crud` | Yes | base_directories, default_timeout, max_timeout, diff_context_lines, max_file_size_bytes | Yes |
| `persistence` | Yes | enabled, state_file, write_debounce_seconds, ttl_multiplier | Yes |
| `watcher` | Yes | enabled, debounce_ms | Yes |

*Note: 4 additional config sections (ShellConfig, SearchConfig, AuditConfig, ProjectConfig) were added post-sprint. See B.7.*

#### B.4.2 CrudConfig Value Drift at Sprint 4

| Setting | PRD Default | Sprint 4 Default | Delta |
|---------|-------------|-------------------|-------|
| `max_file_size_bytes` | 10,485,760 (10MB) | 10,485,760 (10MB) | **Match** |
| `access_rules` | Not in PRD | `list[PathRule]` | Extension (added `673dfa2`, between Sprint 3 and 4) |
| `default_destructive_policy` | Not in PRD | `"allow"` | Extension (added with access_rules) |
| `default_read_policy` | Not in PRD | `"allow"` | Extension (added with access_rules) |

**Analysis**: At Sprint 4 completion, `max_file_size_bytes` matched the PRD exactly (10MB). The increase to 256MB happened post-sprint. The access rules system was added manually between Sprint 3 and Sprint 4 (`673dfa2`), outside sprint orchestration, as a security extension.

*Note: `content_scan_rules` and the `max_file_size_bytes` increase to 256MB were added post-sprint. See B.7.*

### B.5 Dependency Drift (at Sprint 4 Completion)

At `6e8d330`, pyproject.toml dependencies:

| Dependency | PRD Section 6 | Sprint 4 State | Status |
|------------|---------------|----------------|--------|
| `fastmcp>=2.0` | Yes | Yes | Match |
| `pydantic>=2.0` | Yes | Yes | Match |
| `pydantic-settings>=2.0` | Yes | Yes | Match |
| `typer>=0.9` | Yes | Yes | Match |
| `rich>=13.0` | Yes | Yes | Match |
| `loguru>=0.7` | Yes | Yes | Match |
| `tenacity>=8.0` | Yes | Yes | Match |
| `httpx>=0.24` | Yes | Yes | Match |
| `watchdog>=4.0` | Yes | Yes | Match |
| `python-dotenv>=1.0` | Yes | Yes | Match |
| `pywin32>=306` | Yes | Yes | Match |
| `requires-python` | `>=3.12` | `>=3.10` | **Relaxed** (Sprint 4 Story 6) |
| `mcp>=1.0.0` | **Not in PRD** | Yes | Added during Sprint 4 (Story 6) |

**Analysis**: At Sprint 4 completion, 11 of 11 PRD dependencies were present and matching. One extra dependency (`mcp>=1.0.0`) was added by Sprint 4 Story 6. `requires-python` was intentionally relaxed from `>=3.12` to `>=3.10` for broader compatibility (also Story 6).

*Note: `anyio>=4.0` and `mnemonic>=0.20` were added post-sprint (`18c594d` and later). See B.7.*

### B.6 Core Component Compliance

#### B.6.1 Lock Manager (PRD Section 4.1) - COMPLIANT

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| Per-file read/write locking | `FileLock` class with shared reads, exclusive writes | OK |
| FIFO queue semantics | `deque[LockEntry]` with `_promote_next()` batch promotion | OK |
| Write timeout | `asyncio.wait_for()` with configurable timeout | OK |
| Read no-timeout | Reads wait indefinitely (per PRD) | OK |
| TTL-based expiry | `ttl_expires_at` field, `purge_expired()` method | OK |
| Dual-lock for rename | `acquire_dual_write()` with alphabetical ordering | OK |
| Starvation prevention | Write queued -> new reads queue behind it | OK |
| Snapshot/restore | `snapshot()` and `restore()` for persistence | OK |

**Verdict**: Lock manager is fully PRD-compliant. No drift detected.

#### B.6.2 File I/O (PRD Section 4.2) - COMPLIANT

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| Atomic writes via temp+rename | `atomic_write()` with `mkstemp` + `os.replace` | OK |
| SHA-256 hashing | `compute_hash()` returns `sha256:<hex>` | OK |
| Windows retry on PermissionError | `_replace_with_retry()` with tenacity (3 attempts) | OK |
| Cross-filesystem fallback | `safe_rename()` detects via `st_dev` comparison | OK |
| Parent dir fsync (Linux) | `_fsync_parent_directory()` | OK |
| HashRegistry | In-memory dict with path normalization | OK |

**Verdict**: File I/O layer is fully PRD-compliant, including all Section 13 guardrails (13.10, 13.14).

#### B.6.3 Diff Engine (PRD Section 4.3) - COMPLIANT

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| JSON diff format | `compute_json_diff()` with DiffChange regions | OK |
| Unified diff format | `compute_unified_diff()` with standard output | OK |
| Context lines | Configurable `context_lines` parameter | OK |
| Summary with counts | `DiffSummary` model with all 4 counts | OK |
| difflib-based | Uses `SequenceMatcher` and `unified_diff` | OK |

**Extra**: `check_patch_applicability()` function exists for contention resolution (PRD mentions this concept in Section 3.3 response format but doesn't specify implementation).

**Verdict**: Diff engine is fully PRD-compliant.

#### B.6.4 Path Validator (PRD Section 4.4) - COMPLIANT + EXTENDED

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| Base directory whitelist | `_resolved_bases` with prefix matching | OK |
| Symlink resolution | `os.path.realpath()` before validation | OK |
| `..` traversal rejection | Defense-in-depth check after normalization | OK |
| Case normalization (Windows) | `os.path.normcase()` | OK |

**Extensions beyond PRD** (added `673dfa2`, between Sprint 3 and Sprint 4, outside sprint orchestration):
- `access_rules: list[PathRule]` - per-operation access control with priority ordering
- `validate_operation()` - operation-type-aware validation (read/write/delete)
- Glob pattern matching for rules (`fnmatch`)
- Default policy for destructive vs read operations
- `AccessDeniedError` separate from `PathValidationError`

**Verdict**: Core PRD requirements met. Access rules are a significant extension added manually between sprints, not by sprint orchestration.

#### B.6.5 Persistence (PRD Section 4.5) - COMPLIANT

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| Hash registry persistence | `state.json` with `hash_registry` key | OK |
| Pending queue persistence | `state.json` with `pending_queue` key | OK |
| Debounced writes | `mark_dirty()` with `call_later` timer | OK |
| TTL purge on startup | `purge_expired()` called after `restore()` | OK |
| Hash re-validation | `_revalidate_hashes()` checks files on disk | OK |
| Atomic write for state file | Uses `atomic_write()` | OK |

**Verdict**: Persistence layer is fully PRD-compliant.

#### B.6.6 File Watcher (PRD Section 4.6) - COMPLIANT

| PRD Requirement | Implementation | Status |
|----------------|----------------|--------|
| watchdog-based monitoring | `Observer` with `PollingObserver` fallback | OK |
| 100ms debounce | `_DebouncedEventHandler` with configurable window | OK |
| Coalesce DELETE+CREATE -> MODIFY | Explicit coalesce logic in `_add_event()` | OK |
| Network path detection | `_is_network_path()` for UNC and /mnt/ | OK |
| inotify limit fallback | Catches `OSError` and falls back to polling | OK |
| Hash registry integration | Updates on MODIFY/CREATE, removes on DELETE | OK |

**Verdict**: File watcher is fully PRD-compliant, including all Section 13.12 guardrails.

### B.7 Post-Sprint Feature Timeline

These features were added AFTER Sprint 4 orchestration completed (`6e8d330`), in chronological order (oldest first). Total: **29 commits** across installer fixes, shell extension, audit logging, security hardening, and content scanning.

| Commit | Feature | Category |
|--------|---------|----------|
| `51db4f9` | pythonXY._pth with stdlib paths for pythonservice.exe | Installer fix |
| `77ab19a` | Claude Code CLI config + port discovery manifest | Installer |
| `251a3a2` | Add test option to interactive menu | Installer |
| `1461d58` | Shell extension implementation plan | Docs |
| `18c594d` | async_exec, async_wait, async_search tools + ShellConfig, SearchConfig | Shell extension |
| `353193b` | Harden shell exec security + background task lifecycle | Shell security |
| `15df7d9` | Structured audit logging for all MCP tool calls | Audit system |
| `232c0c5` | Harden shell exec: env re-injection, cwd escape, null bytes | Shell security |
| `d8a20d6` | Allow FD redirects in echo/printf deny patterns | Shell security |
| `c94dba5` | Pydantic ValidationError middleware + input constraints | Server middleware |
| `0aa5d39` | Create logs dir, contention error_code, validate search path | Bugfixes |
| `77bff23` | 3-tier hierarchical logging with loguru sinks | Audit system |
| `fbc2c8e` | Sprint completion wrap-up commit | Meta |
| `07e2b57` | FastMCP 3.0 ValidationError middleware (structured_content) | Server middleware |
| `f6aa375` | Timeout clamping + empty pattern rejection | Shell hardening |
| `5ce430b` | Process tree kill, PID persistence, stale timeout, orphan cleanup | Shell hardening |
| `47744a5` | PID reuse guard for orphan cleanup | Shell hardening |
| `c274fe1` | Creation-time based PID verification | Shell hardening |
| `aecd88c` | 14 shell denylist bypass vector blocks | Shell security |
| `ed5cf09` | Block env var concat, array construction, function bypasses | Shell security |
| `48277b6` | Align test assertions with sc failure call + python -c deny | Test fixes |
| `508fad1` | Windows SCM failure recovery with exponential backoff | Daemon |
| `680317c` | Process guard + relax shell deny patterns | Shell security |
| `7b14d19` | Default content scan rules (AWS keys, API keys, etc.) | Content scanning |
| `db90217` | BIP-39 mnemonic detection with function-word heuristic | Content scanning |
| `93628a4` | Hex key pattern tuning for multi-chain compat | Content scanning |
| `754637f` | Content scanner on contention diffs | Content scanning |
| `6eac798` | Smart redaction with semantic placeholders | Content scanning |
| `b046b65` | max_file_size_bytes enforcement on all write paths | Security (partially in PRD) |

**Analysis**: 29 commits after Sprint 4 added substantial features in 6 categories: installer fixes (3), shell extension + security (13), audit logging (2), server middleware (2), content scanning (5), daemon (1), docs (1), test fixes (1), meta (1). These represent incremental manual work outside sprint orchestration. None of this is PRD drift - it's organic feature evolution beyond v0.1.0 scope.

---

## Appendix C: Drift Summary Matrix (at Sprint 4 Completion)

### C.1 What Matches the PRD (Compliant at `6e8d330`)

- All 11 PRD-specified MCP tool signatures and parameters - exact match
- All 6 PRD-specified core components (lock_manager, file_io, diff_engine, path_validator, persistence, file_watcher)
- Lock manager FIFO semantics, timeout handling, dual-lock ordering
- Atomic write pattern with Windows retry and cross-filesystem fallback
- JSON and unified diff formats with summary
- File watcher with debounce, coalesce, and observer fallback
- Persistence with debounced writes, TTL purge, hash re-validation
- All 14 PRD error codes - exact match (no extras, no missing)
- 11 of 11 PRD dependencies present (versions match)
- `max_file_size_bytes` = 10MB (matches PRD)
- ContentionResponse fields match PRD exactly

### C.2 What Still Drifts From the PRD (at Sprint 4 Completion)

| Item | PRD Says | Sprint 4 Actual | Severity | Fixable? |
|------|----------|-----------------|----------|----------|
| `daemon/windows/` directory | Nested subdirectory | Files flat under `daemon/` | Medium | Yes but would break imports |
| CLI file names | `bootstrap.py`, `daemon.py`, etc. | `bootstrap_cmd.py`, `daemon_cmd.py`, etc. | Low | Intentional (module conflict avoidance) |
| `requires-python` | `>=3.12` | `>=3.10` | Low | Intentional (wider compat, Sprint 4 Story 6) |
| `daemon/session_detector.py` location | `daemon/windows/session_detector.py` | `daemon/session_detector.py` | Medium | Same as windows/ directory issue |
| Extra dependency: `mcp>=1.0.0` | Not listed in PRD Section 6 | Present | Low | Needed for MCP protocol (Sprint 4 Story 6) |

### C.3 Sprint-Era Extensions (not in PRD but added during/between sprints)

| Category | Items | Added By |
|----------|-------|----------|
| Access control | PathRule, validate_operation(), destructive/read policies | `673dfa2` (between Sprint 3 and 4) |
| Health MCP tool | health_tool (duplicate of HTTP /health) | Sprint 1 Story 13 |

### C.4 Post-Sprint Feature Additions (outside sprint scope)

| Category | Items | Commit Range |
|----------|-------|-------------|
| Shell execution tools | async_exec, async_wait, async_search | `18c594d` - `b046b65` |
| Security modules | content_scanner, shell_validator, process_guard | `18c594d` - `b046b65` |
| Audit system | audit_logger with 3-tier JSONL sinks | `15df7d9` - `77bff23` |
| Project config tools | crud_activate_project, crud_get_config, crud_update_config | Post-sprint |
| Config sections | ShellConfig, SearchConfig, AuditConfig, ProjectConfig | Post-sprint |
| Extra error codes | 7 new codes for shell/search/validation | Post-sprint |
| Extra response models | 6 new models for exec/wait/search | Post-sprint |
| ContentionResponse extensions | error_code, redacted, redacted_pattern, redacted_hint, redactions | Post-sprint |
| CrudConfig value change | max_file_size_bytes: 10MB -> 256MB | Post-sprint |
| Extra dependencies | `anyio>=4.0`, `mnemonic>=0.20` | Post-sprint (`18c594d`, later) |

---

## Appendix D: Recommendations Update (R8-R12)

### R8: Track Post-PRD Feature Additions as PRD Amendments

The 29 post-sprint commits represent significant functionality (shell execution, content scanning, audit logging) with no PRD coverage. For CREATE_SPRINT accuracy, the PRD should be updated (or a "PRD v2" created) when features grow significantly beyond the original scope. Otherwise, future sprints against the same PRD will generate stories that don't account for the new features.

### R9: Distinguish "Drift" From "Evolution" in Validation

Gate 4 validation should distinguish between:
- **Negative drift**: Implementation doesn't match PRD (bug/omission) - requires fix
- **Positive drift**: Implementation adds features beyond PRD (evolution) - requires PRD update
- **Intentional deviation**: Implementation deliberately differs from PRD (e.g., `_cmd` suffix) - requires ADR

### R10: Include Structural Validation in Gate 4

Current Gate 4 validates story acceptance criteria. It should also validate:
- File tree matches PRD Section 2.3 (or documents exceptions)
- `__init__.py` exports match expected public API
- pyproject.toml dependencies match PRD Section 6 (or documents additions)

### R11: Security Features Need Their Own PRD Section

The content scanner, shell validator, process guard, and audit logger represent a significant security layer. This should be documented in a PRD Section 9 expansion (currently just path validation and network binding).

### R12: Default Config Values Should Be PRD-Pinned

When the PRD specifies a default value (e.g., `max_file_size_bytes: 10MB`), changing it should require an explicit story or ADR. At Sprint 4 completion this value matched the PRD; the change to 256MB happened post-sprint as a manual code change. Gate 4 should verify config defaults match PRD, and post-sprint changes to PRD-specified values should trigger a PRD amendment.
