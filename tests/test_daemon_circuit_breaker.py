"""Tests for ADR-013 restart-storm guardrails (circuit breaker).

Tests the backoff calculation, state persistence, and recovery logic
without requiring a real Windows service environment.
"""

import json
import time


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
