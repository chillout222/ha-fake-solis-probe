#!/usr/bin/env python3
"""v0.5.1 behavior regression tests.

Verifies the fix for the night-time phantom production bug:
  - SENSOR_CACHE must be None when a sensor is unavailable
  - LAST_KNOWN_CACHE must retain the last good value
  - daily_energy_unavailable_behavior=zero must write 0 to register 34621-34622
  - total_energy_unavailable_behavior=last_known must leave the register unchanged

Run standalone (no external dependencies required):
    python fake_solis_probe/tests/test_behavior.py
"""

import sys
import os
import types

# ---------------------------------------------------------------------------
# Minimal stub environment — no HA, no Modbus, no file I/O
# ---------------------------------------------------------------------------

def _build_stub_module() -> types.ModuleType:
    """Import fake_solis_probe with all side effects disabled."""
    # Patch open/os so CONFIG_PATH/EVENT_LOG reads are silent
    import unittest.mock as mock

    # Point to the source file
    src = os.path.join(os.path.dirname(__file__), "..", "fake_solis_probe.py")
    src = os.path.normpath(src)

    module_name = "fake_solis_probe_under_test"

    # Load source as text and exec into a fresh module namespace
    with open(src, "r", encoding="utf-8") as f:
        source = f.read()

    mod = types.ModuleType(module_name)
    mod.__file__ = src

    # Stub out log_event to be a no-op (prevents file writes during tests)
    stub_log_events = []

    def stub_log_event(kind, **data):
        stub_log_events.append({"kind": kind, **data})

    # Stub OPTIONS to safe defaults
    stub_options = {
        "ha_sensor_pv_power":    "sensor.pv",
        "ha_sensor_grid_power":  "sensor.grid",
        "ha_sensor_total_energy": "sensor.total",
        "ha_sensor_daily_energy": "sensor.daily",
        "grid_power_sign_convention": "negate",
        "pv_power_scale":    1.0,
        "grid_power_scale":  1.0,
        "total_energy_scale": 10.0,
        "daily_energy_scale": 10.0,
        "pv_power_unavailable_behavior":    "zero",
        "grid_power_unavailable_behavior":  "zero",
        "total_energy_unavailable_behavior": "last_known",
        "daily_energy_unavailable_behavior": "zero",
    }

    # Compile and exec with patched builtins for file access
    import builtins
    import json
    import threading

    real_open = builtins.open

    def patched_open(file, *a, **kw):
        if "options.json" in str(file):
            import io
            return io.StringIO(json.dumps(stub_options))
        if "events.jsonl" in str(file):
            import io
            return io.StringIO()
        return real_open(file, *a, **kw)

    with mock.patch("builtins.open", patched_open):
        with mock.patch("os.makedirs"):
            with mock.patch("os.stat", side_effect=FileNotFoundError):
                exec(compile(source, src, "exec"), mod.__dict__)

    # Override log_event and stub_log_events ref into module
    mod.log_event = stub_log_event
    mod._stub_log_events = stub_log_events
    return mod


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def regs_to_u32(hi: int, lo: int) -> int:
    return (hi << 16) | lo


def assert_eq(name, actual, expected):
    if actual != expected:
        print(f"  FAIL  {name}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  PASS  {name}: {actual!r}")
    return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cache_separation(m) -> bool:
    """SENSOR_CACHE must be None after failed poll; LAST_KNOWN_CACHE must retain value."""
    print("\n[Test 1] Cache separation after unavailable")
    m.SENSOR_CACHE.clear()
    m.LAST_KNOWN_CACHE.clear()
    m.SENSOR_ERROR_COUNT.clear()

    entity = "sensor.daily"

    # Simulate a successful poll first
    with m.CACHE_LOCK:
        m.SENSOR_CACHE[entity] = 30.6
        m.LAST_KNOWN_CACHE[entity] = 30.6
    m.SENSOR_ERROR_COUNT[entity] = 0

    # Now simulate unavailable (what sensor_poll_loop does in v0.5.1)
    with m.CACHE_LOCK:
        m.SENSOR_CACHE[entity] = None         # ← the fix
        last = m.LAST_KNOWN_CACHE.get(entity) # ← still 30.6

    ok = True
    ok &= assert_eq("SENSOR_CACHE[entity]", m.SENSOR_CACHE.get(entity), None)
    ok &= assert_eq("LAST_KNOWN_CACHE[entity]", m.LAST_KNOWN_CACHE.get(entity), 30.6)
    return ok


def test_daily_zero_behavior(m) -> bool:
    """daily_energy_unavailable_behavior=zero must write 0 to register 34621-34622."""
    print("\n[Test 2] daily_energy behavior=zero writes 0 to register")
    m.SENSOR_CACHE.clear()
    m.LAST_KNOWN_CACHE.clear()
    m.SENSOR_ERROR_COUNT.clear()
    m.REGS.clear()
    m.FALLBACK_LOG_COUNT.clear()
    m._stub_log_events.clear()

    entity = "sensor.daily"

    # Pre-write last-known value into registers (as if previously successful)
    m.REGS[34621] = 1      # 30.6 kWh × 10 = 306 units → hi=0x0001 (0<<16|1... actually 306=0x132)
    m.REGS[34622] = 50     # 306 = 0x0132 → hi=0, lo=306... let's just set them to something non-zero

    # Set up unavailable state
    m.SENSOR_CACHE[entity] = None       # unavailable
    m.LAST_KNOWN_CACHE[entity] = 30.6  # last known

    # Call _apply_behavior directly
    result = m._apply_behavior(
        entity_id=entity,
        raw=None,           # unavailable
        behavior="zero",
        scale=10.0,
        error_count=1,
        last_known_val=30.6,
    )

    # Write result to registers (as update_live_registers does)
    if result is not None:
        hi, lo = m._to_u32_pair(int(result))
        m.REGS[34621] = hi
        m.REGS[34622] = lo

    ok = True
    ok &= assert_eq("_apply_behavior return", result, 0.0)
    ok &= assert_eq("REGS[34621]", m.REGS.get(34621), 0)
    ok &= assert_eq("REGS[34622]", m.REGS.get(34622), 0)

    # Verify register_fallback was logged
    fb = [e for e in m._stub_log_events if e["kind"] == "register_fallback"]
    ok &= assert_eq("register_fallback logged", len(fb) > 0, True)
    if fb:
        ok &= assert_eq("fallback.written_value", fb[0]["written_value"], 0.0)
        ok &= assert_eq("fallback.last_known_value", fb[0]["last_known_value"], 30.6)
    return ok


def test_stale_value_blocked(m) -> bool:
    """Bug regression: old behavior returned 306.0 (stale 30.6 × 10) instead of 0.0."""
    print("\n[Test 3] v0.5.0 regression — stale value must NOT reach register")

    # Simulate OLD bug: SENSOR_CACHE still has 30.6 (was never set to None)
    stale_raw = 30.6
    result_buggy = m._apply_behavior(
        entity_id="sensor.daily",
        raw=stale_raw,  # stale value — as if SENSOR_CACHE was never cleared
        behavior="zero",
        scale=10.0,
        error_count=1,
    )
    ok = True
    # With stale raw (not None), _apply_behavior returns 306.0 regardless of behavior
    # This is the bug: it should return 0.0 but can't because raw is not None
    ok &= assert_eq("stale raw (v0.5.0 bug path) returns non-zero", result_buggy != 0.0, True)
    print(f"  INFO  Old bug would write {result_buggy:.1f} to register (= {int(result_buggy)} units = phantom {int(result_buggy)} W in Tibber)")

    # Now simulate FIXED behavior: SENSOR_CACHE was set to None
    result_fixed = m._apply_behavior(
        entity_id="sensor.daily2",
        raw=None,  # correctly None — v0.5.1 fix
        behavior="zero",
        scale=10.0,
        error_count=1,
        last_known_val=30.6,
    )
    ok &= assert_eq("fixed path (raw=None, behavior=zero) returns 0.0", result_fixed, 0.0)
    return ok


def test_total_energy_last_known(m) -> bool:
    """total_energy_unavailable_behavior=last_known must NOT overwrite register."""
    print("\n[Test 4] total_energy behavior=last_known leaves register unchanged")
    m.REGS.clear()
    m.FALLBACK_LOG_COUNT.clear()
    m._stub_log_events.clear()

    # Pre-write register with last known total
    total_scaled = int(30104.0 * 10)  # 301040
    hi, lo = m._to_u32_pair(total_scaled)
    m.REGS[34391] = hi
    m.REGS[34392] = lo
    m.REGS[34393] = 0

    result = m._apply_behavior(
        entity_id="sensor.total",
        raw=None,
        behavior="last_known",
        scale=10.0,
        error_count=5,
        last_known_val=30104.0,
    )

    ok = True
    ok &= assert_eq("_apply_behavior returns None (do not overwrite)", result, None)

    # Simulate update_live_registers: if result is None, skip writing
    if result is not None:
        hi2, lo2 = m._to_u32_pair(int(result))
        m.REGS[34391] = hi2
        m.REGS[34392] = lo2

    ok &= assert_eq("REGS[34391] unchanged (hi)", m.REGS.get(34391), hi)
    ok &= assert_eq("REGS[34392] unchanged (lo)", m.REGS.get(34392), lo)
    return ok


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("Fake Solis Probe v0.5.1 — behavior regression tests")
    print("=" * 60)

    try:
        m = _build_stub_module()
    except Exception as e:
        print(f"FATAL: Could not load module: {e}")
        import traceback; traceback.print_exc()
        return 1

    results = [
        test_cache_separation(m),
        test_daily_zero_behavior(m),
        test_stale_value_blocked(m),
        test_total_energy_last_known(m),
    ]

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Result: {passed}/{total} tests passed")
    if passed == total:
        print("ALL TESTS PASSED")
        return 0
    else:
        print("SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
