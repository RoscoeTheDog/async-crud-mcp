# Gate 3: Integration Testing (v5.6.0)

Unified test gate: estimate timeout, capture baseline (first entry), run suite, compute diff.

**INLINE EXECUTION REQUIRED**: You MUST run all commands DIRECTLY in your own context using Bash(). Do NOT dispatch subagents, do NOT use /context:TASK, do NOT use Task tool, do NOT use Bash(run_in_background=true) with $CLAUDE_CLI. You are already a subagent -- execute everything inline.

## Instructions

PY="$HOME/.claude/resources/.venv/Scripts/python.exe"
QH="$HOME/.claude/resources/commands/sprint/scripts/queue_helpers.py"

### STEP 1: Check for Existing Baseline

```bash
"$PY" "$QH" checkpoint-read
```

Parse `phase_3_state.baseline` from checkpoint:
- If exists (remediation loop): skip to STEP 4
- If missing (first entry): proceed to STEP 2

Also check `phase_3_state.timeout_estimates`:
- If exists: reuse estimated_timeout from it, skip to STEP 3
- If missing: proceed to STEP 2

### STEP 2: Timeout Estimation

Phase 1 (static scan, ~5-10s):
```bash
"$PY" "$QH" estimate-test-timeout --phase1-only
```

Parse the JSON output. Extract `estimated_timeout` and `high_risk_files`.

Phase 2 (LLM analysis, only if estimation_method == "static_pending_llm"):
- Read the top-N files from `high_risk_files` directly
- Analyze per delegate: `$RESOURCES/sprint/delegates/test-timeout-estimation.md`
- Produce JSON with `timeout_multiplier` and `per_category_adjustments`
- Apply: `"$PY" "$QH" estimate-test-timeout --phase2 --static-result '<phase1_json>' --llm-result '<llm_json>'`

Use the final `estimated_timeout` for all subsequent test runs.

### STEP 3: Capture Baseline

```bash
"$PY" "$QH" capture-test-baseline --timeout $ESTIMATED_TIMEOUT
```

This runs the pre-implementation test suite with retry-with-split auto-healing.
Stores results in `phase_3_state.baseline` and `phase_3_state.timeout_estimates`.

**HALT condition**: If result has `"success": false`, report the error to orchestrator and STOP.
Do NOT proceed with empty baseline -- the differential will be meaningless.

**Greenfield exception**: If result has `"skipped": true, "reason": "no_tests_found"`, proceed normally.
Gate 3 diff will fall back to treating all failures as sprint-scoped.

### STEP 4: Run Post-Implementation Test Suite

Use the same test command and estimated timeout from STEP 2 (or reused from checkpoint).

```bash
"$PY" "$QH" checkpoint-read
```
Extract `estimated_timeout` from `phase_3_state.timeout_estimates.estimated_timeout`.

Run the full test suite with structured output flags:
- **IMPORTANT**: Use file redirect (`> file 2>&1`), NOT pipes (`| tee`). Pipes hang on MSYS/Windows.
- Build command: `pytest --junit-xml=$OUTDIR/gate3-test-results.xml --timeout=60 --timeout_method=thread > $OUTDIR/gate3-test-output.txt 2>&1`
- Use `timeout=$ESTIMATED_TIMEOUT_MS` on the Bash tool call
- If timeout: retry-without-flags fallback
- Parse results: `"$PY" "$QH" parse-test-results --junit-xml "$OUTDIR/gate3-test-results.xml"`

Record results via checkpoint-update:
`"$PY" "$QH" checkpoint-update '{"phase_3_state": {"results": {"exit_code": N, "passed": N, "failed": N, "skipped": N, "total": N, "failed_tests": [...], "raw_output_path": "...", "junit_xml_path": "..."}}}' --minimal`

### STEP 5: Compute Differential

```bash
"$PY" "$QH" compute-test-diff
```

Reads baseline and post-impl results from `phase_3_state`, computes set difference.
Writes `phase_3_state.baseline_diff` to checkpoint.

### STEP 6: Record Completion

```bash
"$PY" "$QH" checkpoint-update '{"phase_status": {"3": "completed"}}' --minimal
```

Do NOT create remediation stories. Only record results. Gate 5 handles remediation.
