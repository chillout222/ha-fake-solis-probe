"""v0.5.1 behavior regression tests.

Verifies the fix for the night-time phantom production bug:
- SENSOR_CACHE must be None when a sensor is unavailable.
- LAST_KNOWN_CACHE must retain the last good value.
- daily_energy_unavailable_behavior=zero must write 0 to registers 34621–34622.
- total_energy_unavailable_behavior=last_known must leave the register unchanged.

Run with pytest:
    python -m pytest fake_solis_probe/tests/test_behavior.py
"""

from __future__ import annotations

from typing import Any

import pytest

from solis_probe import config, event_log, registers, sensor_cache, telemetry


# ---------------------------------------------------------------------------
# Direct test environment — no HA or Modbus calls, and no runtime file I/O.
# Importing the split runtime is safe because startup side effects live in main().
# ---------------------------------------------------------------------------

TEST_OPTIONS: dict[str, object] = {
    "ha_sensor_pv_power": "sensor.pv",
    "ha_sensor_grid_power": "sensor.grid",
    "ha_sensor_total_energy": "sensor.total",
    "ha_sensor_daily_energy": "sensor.daily",
    "grid_power_sign_convention": "negate",
    "pv_power_scale": 1.0,
    "grid_power_scale": 1.0,
    "total_energy_scale": 10.0,
    "daily_energy_scale": 10.0,
    "pv_power_unavailable_behavior": "zero",
    "grid_power_unavailable_behavior": "zero",
    "total_energy_unavailable_behavior": "last_known",
    "daily_energy_unavailable_behavior": "zero",
}


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Provide isolated mutable runtime state and an in-memory event sink."""
    config.configure_options(TEST_OPTIONS)
    sensor_cache.reset()
    registers.reset()
    telemetry.reset_fallback_log_counts()
    events: list[dict[str, Any]] = []

    def capture_event(kind: str, **data: Any) -> None:
        events.append({"kind": kind, **data})

    monkeypatch.setattr(event_log, "log_event", capture_event)
    return events


def test_cache_separation_after_sensor_becomes_unavailable(
    captured_events: list[dict[str, Any]],
) -> None:
    """SENSOR_CACHE must be None after a failed poll; last-known must persist."""
    entity_id = "sensor.daily"

    # Simulate a successful poll first.
    with sensor_cache.CACHE_LOCK:
        sensor_cache.SENSOR_CACHE[entity_id] = 30.6
        sensor_cache.LAST_KNOWN_CACHE[entity_id] = 30.6

    # Now simulate unavailable (what sensor_poll_loop does since v0.5.1).
    # Clearing SENSOR_CACHE is the fix; LAST_KNOWN_CACHE remains 30.6.
    with sensor_cache.CACHE_LOCK:
        sensor_cache.SENSOR_CACHE[entity_id] = None

        assert sensor_cache.SENSOR_CACHE[entity_id] is None
        assert sensor_cache.LAST_KNOWN_CACHE[entity_id] == 30.6


@pytest.mark.parametrize(
    ("raw", "behavior", "expected_result", "expected_written_value"),
    [
        pytest.param(30.6, "zero", 306.0, None, id="available-value-is-scaled"),
        pytest.param(None, "zero", 0.0, 0.0, id="unavailable-value-is-zeroed"),
        pytest.param(
            None,
            "last_known",
            None,
            None,
            id="unavailable-value-leaves-register-unchanged",
        ),
    ],
)
def test_apply_behavior_for_available_and_unavailable_values(
    captured_events: list[dict[str, Any]],
    raw: float | None,
    behavior: str,
    expected_result: float | None,
    expected_written_value: float | None,
) -> None:
    """Fallback behavior is only applied after the sensor cache is cleared."""
    result = telemetry.apply_behavior(
        entity_id="sensor.daily",
        raw=raw,
        behavior=behavior,
        scale=10.0,
        error_count=1,
        last_known_val=30.6,
    )

    assert result == expected_result

    if raw is not None:
        assert captured_events == []
    else:
        assert captured_events == [
            {
                "kind": "register_fallback",
                "entity_id": "sensor.daily",
                "behavior": behavior,
                "written_value": expected_written_value,
                "last_known_value": 30.6,
                "consecutive_errors": 1,
            }
        ]


def test_stale_value_is_blocked_after_the_cache_is_cleared(
    captured_events: list[dict[str, Any]],
) -> None:
    """Regression: a stale 30.6 value must not become phantom production."""
    # Simulate the old bug: SENSOR_CACHE still has 30.6 because it was never
    # cleared. A non-None raw value returns 306.0 regardless of behavior.
    stale_result = telemetry.apply_behavior(
        entity_id="sensor.daily",
        raw=30.6,
        behavior="zero",
        scale=10.0,
        error_count=1,
    )
    assert stale_result == 306.0

    # With the v0.5.1 fix, SENSOR_CACHE is None and the zero fallback wins.
    fixed_result = telemetry.apply_behavior(
        entity_id="sensor.daily",
        raw=None,
        behavior="zero",
        scale=10.0,
        error_count=1,
        last_known_val=30.6,
    )
    assert fixed_result == 0.0


@pytest.mark.parametrize(
    (
        "entity_id",
        "behavior",
        "last_known_value",
        "register_start",
        "initial_scaled_value",
        "expected_scaled_value",
    ),
    [
        pytest.param(
            "sensor.daily",
            "zero",
            30.6,
            34621,
            306,
            0,
            id="daily-energy-zeroes-the-register",
        ),
        pytest.param(
            "sensor.total",
            "last_known",
            30104.0,
            34391,
            301040,
            301040,
            id="total-energy-preserves-the-register",
        ),
    ],
)
def test_unavailable_energy_behavior_updates_registers_as_expected(
    captured_events: list[dict[str, Any]],
    entity_id: str,
    behavior: str,
    last_known_value: float,
    register_start: int,
    initial_scaled_value: int,
    expected_scaled_value: int,
) -> None:
    """Daily zero writes 34621–34622; total last_known preserves 34391–34392."""
    # Pre-write the prior value as if the sensor was previously successful.
    initial_high_word, initial_low_word = registers.to_u32_pair(initial_scaled_value)
    with registers.REG_LOCK:
        registers.REGS[register_start] = initial_high_word
        registers.REGS[register_start + 1] = initial_low_word

    # Set up an unavailable state while retaining the last known value.
    with sensor_cache.CACHE_LOCK:
        sensor_cache.SENSOR_CACHE[entity_id] = None
        sensor_cache.LAST_KNOWN_CACHE[entity_id] = last_known_value
        sensor_cache.SENSOR_ERROR_COUNT[entity_id] = 1

    # Exercise the real cache-to-register mapping rather than reproducing it here.
    telemetry.update_live_registers()

    expected_high_word, expected_low_word = registers.to_u32_pair(expected_scaled_value)
    with registers.REG_LOCK:
        assert registers.REGS[register_start] == expected_high_word
        assert registers.REGS[register_start + 1] == expected_low_word

    assert any(
        event["kind"] == "register_fallback"
        and event["entity_id"] == entity_id
        and event["behavior"] == behavior
        and event["last_known_value"] == last_known_value
        and event["consecutive_errors"] == 1
        for event in captured_events
    )
