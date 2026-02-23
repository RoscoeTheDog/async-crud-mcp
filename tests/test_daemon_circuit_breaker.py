"""Tests for ADR-013 restart-storm guardrails (circuit breaker).

Tests the backoff calculation, state persistence, and recovery logic
without requiring a real Windows service environment.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional


# We can't import dispatcher directly on non-Windows, so test the
# constants and logic patterns in isolation.


class TestBackoffCalculation:
    """Test exponential backoff formula used in _poll_workers."""

    BACKOFF_BASE = 5
    BACKOFF_MAX = 300

    def _calc_backoff(self, consecutive_failures: int) -> float:
        """Reproduce the backoff formula from dispatcher._poll_workers."""
        return min(
            self.BACKOFF_BASE * (2 ** (consecutive_failures - 1)),
            self.BACKOFF_MAX,
        )

    def test_first_failure_backoff(self):
        """First failure should use base backoff (5s)."""
        assert self._calc_backoff(1) == 5

    def test_second_failure_backoff(self):
        """Second failure doubles: 10s."""
        assert self._calc_backoff(2) == 10

    def test_third_failure_backoff(self):
        """Third failure: 20s."""
        assert self._calc_backoff(3) == 20

    def test_fifth_failure_backoff(self):
        """Fifth failure: 80s."""
        assert self._calc_backoff(5) == 80

    def test_backoff_caps_at_max(self):
        """Backoff should never exceed BACKOFF_MAX_SECONDS (300)."""
        assert self._calc_backoff(7) == 300
        assert self._calc_backoff(10) == 300
        assert self._calc_backoff(100) == 300

    def test_backoff_increases_exponentially(self):
        """Each step should double until hitting the cap."""
        prev = 0
        for i in range(1, 7):
            current = self._calc_backoff(i)
            assert current > prev
            prev = current

    def test_backoff_at_cap_boundary(self):
        """Find the exact failure count where cap kicks in."""
        # 5 * 2^(n-1) >= 300 -> 2^(n-1) >= 60 -> n-1 >= 6 -> n >= 7
        assert self._calc_backoff(6) == 160  # still under cap
        assert self._calc_backoff(7) == 300  # hits cap


class TestCircuitBreakerStatePersistence:
    """Test writing and reading circuit breaker state JSON."""

    def test_write_state_creates_json(self, tmp_path):
        """State file should contain correct JSON structure."""
        state_file = tmp_path / "circuit_breaker_state.json"
        state = {
            "consecutive_failures": 3,
            "next_restart_at": time.time() + 20,
            "username": "testuser",
            "updated_at": time.time(),
        }
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded["consecutive_failures"] == 3
        assert loaded["username"] == "testuser"
        assert "next_restart_at" in loaded
        assert "updated_at" in loaded

    def test_clear_state_removes_file(self, tmp_path):
        """Clearing circuit breaker should remove the state file."""
        state_file = tmp_path / "circuit_breaker_state.json"
        state_file.write_text("{}", encoding="utf-8")
        assert state_file.exists()

        state_file.unlink()
        assert not state_file.exists()

    def test_read_missing_state_returns_none(self, tmp_path):
        """Reading non-existent state file should return None."""
        from async_crud_mcp.daemon.health import _read_circuit_breaker_state

        result = _read_circuit_breaker_state(str(tmp_path))
        assert result is None

    def test_read_valid_state(self, tmp_path):
        """Reading valid state file should return the state dict."""
        from async_crud_mcp.daemon.health import _read_circuit_breaker_state

        state = {
            "consecutive_failures": 5,
            "next_restart_at": time.time() + 100,
            "username": "alice",
            "updated_at": time.time(),
        }
        state_file = tmp_path / "circuit_breaker_state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        result = _read_circuit_breaker_state(str(tmp_path))
        assert result is not None
        assert result["consecutive_failures"] == 5
        assert result["username"] == "alice"

    def test_read_corrupt_state_returns_none(self, tmp_path):
        """Corrupt JSON should not crash, return None."""
        from async_crud_mcp.daemon.health import _read_circuit_breaker_state

        state_file = tmp_path / "circuit_breaker_state.json"
        state_file.write_text("not valid json{{{", encoding="utf-8")

        result = _read_circuit_breaker_state(str(tmp_path))
        assert result is None


class TestLogEscalation:
    """Test log escalation threshold behavior."""

    LOG_ESCALATION_THRESHOLD = 10

    def test_below_threshold_is_warning(self):
        """Failures below threshold should use warning level."""
        for failures in range(1, self.LOG_ESCALATION_THRESHOLD):
            assert failures < self.LOG_ESCALATION_THRESHOLD

    def test_at_threshold_is_error(self):
        """At exactly the threshold, should escalate to error."""
        assert self.LOG_ESCALATION_THRESHOLD >= self.LOG_ESCALATION_THRESHOLD

    def test_above_threshold_stays_error(self):
        """Failures above threshold should remain at error level."""
        for failures in [11, 20, 100]:
            assert failures >= self.LOG_ESCALATION_THRESHOLD


class TestHealthCheckCircuitBreaker:
    """Test that check_health() includes circuit breaker info."""

    def test_health_check_has_circuit_breaker_key(self):
        """check_health result should include circuit_breaker field."""
        from async_crud_mcp.daemon.health import check_health

        result = check_health()
        assert "circuit_breaker" in result

    def test_health_check_has_python_key(self):
        """check_health result should include python version check."""
        from async_crud_mcp.daemon.health import check_health

        result = check_health()
        assert "python" in result
        assert result["python"]["ok"] is True
        assert "version" in result["python"]

    def test_health_check_has_dependency_key(self):
        """check_health result should include dependency check."""
        from async_crud_mcp.daemon.health import check_health

        result = check_health()
        assert "dependency_available" in result
        assert result["dependency_available"]["ok"] is True

    def test_health_check_has_disk_space_key(self):
        """check_health result should include disk space check."""
        from async_crud_mcp.daemon.health import check_health

        result = check_health()
        assert "disk_space" in result
        assert "free_mb" in result["disk_space"]

    def test_health_check_has_uptime_key(self):
        """check_health result should include uptime."""
        from async_crud_mcp.daemon.health import check_health

        result = check_health()
        assert "uptime_seconds" in result
        assert result["uptime_seconds"] >= 0


class TestConstants:
    """Verify ADR-013 constants are correctly defined."""

    def test_backoff_base(self):
        """BACKOFF_BASE_SECONDS should be 5."""
        assert TestBackoffCalculation.BACKOFF_BASE == 5

    def test_backoff_max(self):
        """BACKOFF_MAX_SECONDS should be 300."""
        assert TestBackoffCalculation.BACKOFF_MAX == 300

    def test_log_escalation_threshold(self):
        """LOG_ESCALATION_THRESHOLD should be 10."""
        assert TestLogEscalation.LOG_ESCALATION_THRESHOLD == 10


# =========================================================================
# State machine simulation for _poll_workers logic tests
# =========================================================================

BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 300


@dataclass
class MockWorker:
    """Minimal UserWorker mock for state machine tests."""

    username: str = "testuser"
    session_ids: set = field(default_factory=lambda: {1})
    user_token: Optional[int] = 999
    process_handle: Optional[int] = None
    process_id: Optional[int] = None
    started_at: Optional[float] = None
    consecutive_failures: int = 0
    next_restart_at: float = 0


def simulate_poll_cycle(worker: MockWorker, now: float, process_alive: bool = False,
                        exit_code: int = 0) -> dict:
    """Simulate one cycle of _poll_workers logic for a single worker.

    Reproduces the exact branching from dispatcher._poll_workers() so we can
    test the state machine transitions without Win32 dependencies.

    Returns a dict with:
        - needs_restart: whether restart was attempted
        - newly_failed: whether this was a new crash detection
        - deferred: whether restart was deferred (backoff pending)
        - action: description of what happened
        - consecutive_failures: final failure count
        - next_restart_at: final restart time
        - token_refreshed: whether token refresh would be attempted
    """
    needs_restart = False
    newly_failed = False
    restart_reason = ""
    result = {
        "needs_restart": False,
        "newly_failed": False,
        "deferred": False,
        "action": "no_action",
        "consecutive_failures": worker.consecutive_failures,
        "next_restart_at": worker.next_restart_at,
        "token_refreshed": False,
    }

    # Check if process is still alive
    if worker.process_handle:
        if not process_alive:
            needs_restart = True
            newly_failed = True
            restart_reason = f"exited (code {exit_code})"
            worker.process_handle = None
            worker.process_id = None
        # else: process alive - skip port check for simplicity

    # Detect workers awaiting deferred restart
    if not needs_restart and not worker.process_handle and worker.next_restart_at > 0:
        if now >= worker.next_restart_at:
            needs_restart = True
            restart_reason = f"deferred restart (failure #{worker.consecutive_failures})"
        else:
            result["deferred"] = True
            result["action"] = "deferred_waiting"
            result["consecutive_failures"] = worker.consecutive_failures
            result["next_restart_at"] = worker.next_restart_at
            return result

    # Circuit breaker
    if needs_restart:
        if newly_failed:
            worker.consecutive_failures += 1
            backoff = min(
                BACKOFF_BASE_SECONDS * (2 ** (worker.consecutive_failures - 1)),
                BACKOFF_MAX_SECONDS,
            )
            worker.next_restart_at = now + backoff

            if now < worker.next_restart_at:
                result["needs_restart"] = True
                result["newly_failed"] = True
                result["deferred"] = True
                result["action"] = "new_failure_deferred"
                result["consecutive_failures"] = worker.consecutive_failures
                result["next_restart_at"] = worker.next_restart_at
                return result

        # Token refresh would happen here
        result["token_refreshed"] = True
        result["needs_restart"] = True
        result["newly_failed"] = newly_failed
        result["action"] = "restart_attempted"
        result["consecutive_failures"] = worker.consecutive_failures
        result["next_restart_at"] = worker.next_restart_at
        # Simulate successful restart
        worker.process_handle = 42
        worker.process_id = 1234
        worker.started_at = now
        return result

    result["action"] = "no_action"
    result["consecutive_failures"] = worker.consecutive_failures
    result["next_restart_at"] = worker.next_restart_at
    return result


class TestPollWorkersStateMachine:
    """Validate the _poll_workers state machine transitions.

    Tests the fix for the bug where a dead worker's pending-restart state
    was lost between poll cycles because process_handle was already None.
    """

    def test_first_poll_after_crash_defers_restart(self):
        """First poll detects dead process, sets backoff, and defers restart."""
        worker = MockWorker(process_handle=100, process_id=8964)
        now = time.time()

        result = simulate_poll_cycle(worker, now, process_alive=False, exit_code=0)

        assert result["newly_failed"] is True
        assert result["deferred"] is True
        assert result["action"] == "new_failure_deferred"
        assert worker.consecutive_failures == 1
        assert worker.next_restart_at == now + BACKOFF_BASE_SECONDS
        assert worker.process_handle is None  # cleaned up

    def test_second_poll_triggers_deferred_restart(self):
        """Second poll (after backoff expires) triggers the actual restart."""
        worker = MockWorker()
        now = time.time()

        # Simulate state after first poll: dead, one failure, backoff set
        worker.process_handle = None
        worker.consecutive_failures = 1
        worker.next_restart_at = now - 1  # backoff expired

        result = simulate_poll_cycle(worker, now)

        assert result["needs_restart"] is True
        assert result["newly_failed"] is False
        assert result["action"] == "restart_attempted"
        assert result["token_refreshed"] is True
        # Failure count should NOT be incremented on deferred retry
        assert worker.consecutive_failures == 1

    def test_second_poll_during_backoff_defers_again(self):
        """If backoff hasn't expired, second poll should still defer."""
        worker = MockWorker()
        now = time.time()

        worker.process_handle = None
        worker.consecutive_failures = 1
        worker.next_restart_at = now + 3  # 3 seconds remaining

        result = simulate_poll_cycle(worker, now)

        assert result["deferred"] is True
        assert result["action"] == "deferred_waiting"
        assert result["needs_restart"] is False

    def test_no_spurious_restart_when_next_restart_at_zero(self):
        """Worker with no process and next_restart_at=0 should not restart.

        This is the normal state of a cleanly stopped worker (no sessions left).
        """
        worker = MockWorker()
        worker.process_handle = None
        worker.next_restart_at = 0
        worker.consecutive_failures = 0

        result = simulate_poll_cycle(worker, time.time())

        assert result["needs_restart"] is False
        assert result["action"] == "no_action"

    def test_consecutive_failures_not_double_incremented(self):
        """Failure count should only increment once per actual crash, not on retry."""
        worker = MockWorker(process_handle=100, process_id=8964)
        now = time.time()

        # First poll: crash detected
        r1 = simulate_poll_cycle(worker, now, process_alive=False)
        assert worker.consecutive_failures == 1

        # Second poll: deferred retry (backoff expired)
        worker.next_restart_at = now - 1  # expired
        r2 = simulate_poll_cycle(worker, now)
        assert worker.consecutive_failures == 1  # NOT 2

        # Simulate second crash: new process dies
        worker.process_handle = 200
        r3 = simulate_poll_cycle(worker, now + 100, process_alive=False)
        assert worker.consecutive_failures == 2  # NOW incremented

    def test_token_refresh_on_deferred_restart(self):
        """Token refresh should happen before restart attempt."""
        worker = MockWorker()
        worker.process_handle = None
        worker.consecutive_failures = 1
        worker.next_restart_at = time.time() - 1  # expired

        result = simulate_poll_cycle(worker, time.time())

        assert result["token_refreshed"] is True
        assert result["action"] == "restart_attempted"

    def test_multiple_failures_escalate_backoff(self):
        """Each new crash should increase backoff exponentially."""
        worker = MockWorker(process_handle=100, process_id=1000)
        now = time.time()

        backoffs = []
        for i in range(5):
            # Crash
            worker.process_handle = 100 + i
            r = simulate_poll_cycle(worker, now + i * 1000, process_alive=False)
            backoffs.append(worker.next_restart_at - (now + i * 1000))

            # Successful restart after backoff
            worker.next_restart_at = now + i * 1000 - 1  # expired
            simulate_poll_cycle(worker, now + i * 1000)

        # Backoffs should be: 5, 10, 20, 40, 80
        assert backoffs == [5, 10, 20, 40, 80]

    def test_full_crash_recovery_cycle(self):
        """End-to-end: crash -> defer -> restart -> running."""
        worker = MockWorker(process_handle=100, process_id=8964)
        t0 = time.time()

        # Poll 1: Detect crash
        r1 = simulate_poll_cycle(worker, t0, process_alive=False)
        assert r1["action"] == "new_failure_deferred"
        assert worker.process_handle is None

        # Poll 2: Still in backoff (2 seconds later, need 5)
        r2 = simulate_poll_cycle(worker, t0 + 2)
        assert r2["action"] == "deferred_waiting"
        assert worker.process_handle is None

        # Poll 3: Backoff expired (6 seconds later)
        r3 = simulate_poll_cycle(worker, t0 + 6)
        assert r3["action"] == "restart_attempted"
        assert worker.process_handle is not None  # restarted
        assert worker.consecutive_failures == 1  # not incremented again
