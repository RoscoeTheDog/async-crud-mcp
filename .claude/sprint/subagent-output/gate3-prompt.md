# Gate 3: Integration Testing

Run the full test suite and record results.

**INLINE EXECUTION REQUIRED**: You MUST run all commands DIRECTLY in your own context using Bash(). Do NOT dispatch subagents, do NOT use /context:TASK, do NOT use Task tool, do NOT use Bash(run_in_background=true) with $CLAUDE_CLI. You are already a subagent -- execute everything inline. If a Bash call is auto-backgrounded due to timeout, do NOT use TaskOutput to wait -- instead use `Bash("sleep 30")` then check the output file directly. NEVER call TaskOutput.

IMPORTANT: Skip INIT protocol entirely. Do not run any MCP activation or Graphiti steps.

## Instructions

1. Run the test suite using the Bash tool with an explicit timeout:
   `Bash("pytest 2>&1 | tee .claude/sprint/subagent-output/gate3-test-output.txt; echo EXIT_CODE=$?", timeout=1200000)`
   Store the exit code from the output.
2. Parse test output to extract passed/failed/total counts from the output file.
3. Record results via checkpoint-update:
   ```
   PY="$HOME/.claude/resources/.venv/Scripts/python.exe"
   QH="$HOME/.claude/resources/commands/sprint/scripts/queue_helpers.py"
   "$PY" "$QH" checkpoint-update '{"phase_3_state": {"results": {"exit_code": TEST_EXIT, "passed": N, "failed": N, "total": N, "raw_output_path": ".claude/sprint/subagent-output/gate3-test-output.txt"}}}' --minimal
   ```
4. Mark complete:
   ```
   "$PY" "$QH" checkpoint-update '{"phase_status": {"3": "completed"}}' --minimal
   ```

**IMPORTANT**: You MUST use `timeout=1200000` on the Bash tool call. The default 120s Bash timeout will kill long test suites.

Do NOT create remediation stories. Only record results. Gate 5 handles remediation.
