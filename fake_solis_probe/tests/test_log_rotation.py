#!/usr/bin/env python3
"""Log rotation tests — v0.7.0.

Tests _rotate_log_if_needed() using a real temporary directory and real file I/O
so that os.path.getsize / os.replace / os.path.exists exercise actual disk behaviour.

Run standalone (no external dependencies required):
    python fake_solis_probe/tests/test_log_rotation.py
"""

import os
import sys
import json
import types
import tempfile
import shutil
import unittest.mock as mock
import builtins


# ---------------------------------------------------------------------------
# Module loader (same pattern as test_behavior.py)
# ---------------------------------------------------------------------------

def _build_stub_module(event_log: str, options: dict) -> types.ModuleType:
    """Load fake_solis_probe with I/O side-effects neutralised except for
    the log rotation paths (which use the real os module on `event_log`).
    """
    src = os.path.join(os.path.dirname(__file__), "..", "fake_solis_probe.py")
    src = os.path.normpath(src)

    with open(src, "r", encoding="utf-8") as f:
        source = f.read()

    mod = types.ModuleType("fake_solis_probe_rot_test")
    mod.__file__ = src

    real_open = builtins.open

    def patched_open(file, *a, **kw):
        # Redirect options.json to our stub options
        if "options.json" in str(file):
            import io
            return io.StringIO(json.dumps(options))
        # Let events.jsonl writes go to the real temp path
        return real_open(file, *a, **kw)

    with mock.patch("builtins.open", patched_open):
        with mock.patch("os.makedirs"):          # suppress dir creation at module load
            with mock.patch("os.stat", side_effect=FileNotFoundError):
                exec(compile(source, src, "exec"), mod.__dict__)

    # Point the module at the temp log path
    mod.EVENT_LOG = event_log
    mod.EVENT_DIR = os.path.dirname(event_log)
    # Silence log_event's stdout print and file write during these tests
    mod.log_event = lambda kind, **data: None
    # Apply test options
    mod.OPTIONS.update(options)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_eq(name, actual, expected):
    if actual != expected:
        print(f"  FAIL  {name}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  PASS  {name}: {actual!r}")
    return True


def assert_true(name, value):
    if not value:
        print(f"  FAIL  {name}: expected True, got {value!r}")
        return False
    print(f"  PASS  {name}: True")
    return True


def assert_false(name, value):
    if value:
        print(f"  FAIL  {name}: expected False, got {value!r}")
        return False
    print(f"  PASS  {name}: False")
    return True


def write_bytes(path: str, n: int) -> None:
    """Write n bytes of dummy content to path."""
    with open(path, "wb") as f:
        f.write(b"x" * n)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_rotation_below_threshold(tmpdir: str) -> bool:
    """File size below threshold: rotation must NOT occur."""
    print("\n[Test 1] No rotation below threshold")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 1000, "log_backup_count": 3}
    m = _build_stub_module(event_log, options)

    write_bytes(event_log, 100)  # well below 1000

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_true("events.jsonl still exists", os.path.exists(event_log))
    ok &= assert_false("events.jsonl.1 must NOT exist", os.path.exists(event_log + ".1"))
    ok &= assert_eq("file size unchanged", os.path.getsize(event_log), 100)
    return ok


def test_rotation_triggered(tmpdir: str) -> bool:
    """File size at or above threshold: current log renamed to .1."""
    print("\n[Test 2] Rotation triggered — current log becomes .1")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": 3}
    m = _build_stub_module(event_log, options)

    content = b"A" * 200  # 200 bytes > 100 bytes threshold
    write_bytes(event_log, 200)

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_false("events.jsonl must NOT exist (was renamed)", os.path.exists(event_log))
    ok &= assert_true("events.jsonl.1 must exist", os.path.exists(event_log + ".1"))
    ok &= assert_eq("events.jsonl.1 size", os.path.getsize(event_log + ".1"), 200)
    return ok


def test_cascade_rotation(tmpdir: str) -> bool:
    """Cascade: .2 → .3, .1 → .2, current → .1."""
    print("\n[Test 3] Cascade rotation (.2 -> .3, .1 -> .2, current -> .1)")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": 3}
    m = _build_stub_module(event_log, options)

    # Pre-create existing backups with distinct sizes so we can track them
    write_bytes(event_log,           200)  # current (200 B) — will become .1
    write_bytes(event_log + ".1",    150)  # will become .2
    write_bytes(event_log + ".2",    120)  # will become .3

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_false("events.jsonl must NOT exist", os.path.exists(event_log))
    ok &= assert_eq("events.jsonl.1 size == 200", os.path.getsize(event_log + ".1"), 200)
    ok &= assert_eq("events.jsonl.2 size == 150", os.path.getsize(event_log + ".2"), 150)
    ok &= assert_eq("events.jsonl.3 size == 120", os.path.getsize(event_log + ".3"), 120)
    return ok


def test_cascade_does_not_exceed_backup_count(tmpdir: str) -> bool:
    """Oldest backup beyond backup_count is discarded (overwritten by os.replace)."""
    print("\n[Test 4] Oldest backup beyond backup_count is dropped")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": 2}  # keep only .1 and .2
    m = _build_stub_module(event_log, options)

    write_bytes(event_log,           200)
    write_bytes(event_log + ".1",    150)
    write_bytes(event_log + ".2",    120)  # this gets pushed to .3, but .3 is beyond backup_count=2

    m._rotate_log_if_needed()

    ok = True
    # With backup_count=2: range(1, 0, -1) shifts .1 → .2 only (no .3 step)
    # So .2 gets overwritten by old .1, and current goes to .1
    ok &= assert_false("events.jsonl must NOT exist", os.path.exists(event_log))
    ok &= assert_eq("events.jsonl.1 size == 200", os.path.getsize(event_log + ".1"), 200)
    ok &= assert_eq("events.jsonl.2 size == 150", os.path.getsize(event_log + ".2"), 150)
    ok &= assert_false("events.jsonl.3 must NOT exist", os.path.exists(event_log + ".3"))
    return ok


def test_backup_count_zero_truncates(tmpdir: str) -> bool:
    """backup_count=0: file is truncated in-place, no .1 created."""
    print("\n[Test 5] backup_count=0 -> truncate in-place")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": 0}
    m = _build_stub_module(event_log, options)

    write_bytes(event_log, 200)

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_true("events.jsonl still exists (truncated)", os.path.exists(event_log))
    ok &= assert_eq("events.jsonl size == 0 (truncated)", os.path.getsize(event_log), 0)
    ok &= assert_false("events.jsonl.1 must NOT exist", os.path.exists(event_log + ".1"))
    return ok


def test_max_bytes_zero_disables_rotation(tmpdir: str) -> bool:
    """log_max_bytes=0: rotation disabled; large file left untouched."""
    print("\n[Test 6] log_max_bytes=0 -> rotation disabled")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 0, "log_backup_count": 3}
    m = _build_stub_module(event_log, options)

    write_bytes(event_log, 99_999_999)  # ~100 MB — should not rotate

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_true("events.jsonl still exists", os.path.exists(event_log))
    ok &= assert_false("events.jsonl.1 must NOT exist", os.path.exists(event_log + ".1"))
    return ok


def test_missing_file_does_not_crash(tmpdir: str) -> bool:
    """If events.jsonl does not exist yet, rotation must not raise."""
    print("\n[Test 7] Missing events.jsonl — no crash")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": 3}
    m = _build_stub_module(event_log, options)
    # Do NOT create the file

    raised = False
    try:
        m._rotate_log_if_needed()
    except Exception as exc:
        raised = True
        print(f"  FAIL  unexpected exception: {exc}")

    ok = assert_false("no exception raised", raised)
    ok &= assert_false("events.jsonl.1 must NOT exist", os.path.exists(event_log + ".1"))
    return ok


def test_log_event_integration(tmpdir: str) -> bool:
    """Verify _rotate_log_if_needed() fires correctly when called from within
    the same path log_event() uses — pre-fill to threshold then rotate."""
    print("\n[Test 8] log_event() integration -- rotation via direct call after pre-fill")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 200, "log_backup_count": 2}
    m = _build_stub_module(event_log, options)

    # Pre-fill the file to above the threshold
    write_bytes(event_log, 250)

    # Call the rotation helper directly (same code path log_event() uses)
    m._rotate_log_if_needed()

    ok = True
    ok &= assert_false("events.jsonl must NOT exist after rotation", os.path.exists(event_log))
    ok &= assert_true("events.jsonl.1 must exist", os.path.exists(event_log + ".1"))
    ok &= assert_eq("events.jsonl.1 size == 250", os.path.getsize(event_log + ".1"), 250)
    return ok


def test_backup_count_negative_truncates(tmpdir: str) -> bool:
    """backup_count=-1 (negative): must truncate in-place, must NOT create .1.

    Regression test for the edge case where backup_count < 0 would previously
    bypass the truncate branch (== 0 check) and fall through to the cascade
    loop, which would then unconditionally rename events.jsonl -> events.jsonl.1.
    """
    print("\n[Test 9] backup_count=-1 -> must truncate, not rename to .1 (edge case)")
    event_log = os.path.join(tmpdir, "events.jsonl")
    options = {"log_max_bytes": 100, "log_backup_count": -1}
    m = _build_stub_module(event_log, options)

    write_bytes(event_log, 200)  # above threshold

    m._rotate_log_if_needed()

    ok = True
    ok &= assert_true("events.jsonl still exists (truncated)", os.path.exists(event_log))
    ok &= assert_eq("events.jsonl size == 0 (truncated)", os.path.getsize(event_log), 0)
    ok &= assert_false("events.jsonl.1 must NOT exist", os.path.exists(event_log + ".1"))
    return ok


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("Fake Solis Probe v0.7.0 — log rotation tests")
    print("=" * 60)

    results = []
    tmpdirs = []
    tests = [
        test_no_rotation_below_threshold,
        test_rotation_triggered,
        test_cascade_rotation,
        test_cascade_does_not_exceed_backup_count,
        test_backup_count_zero_truncates,
        test_max_bytes_zero_disables_rotation,
        test_missing_file_does_not_crash,
        test_log_event_integration,
        test_backup_count_negative_truncates,  # edge case: negative value
    ]

    for fn in tests:
        tmpdir = tempfile.mkdtemp(prefix="solis_rot_test_")
        tmpdirs.append(tmpdir)
        try:
            ok = fn(tmpdir)
        except Exception as exc:
            print(f"  FATAL  {fn.__name__}: unhandled exception: {exc}")
            import traceback
            traceback.print_exc()
            ok = False
        results.append(ok)

    # Cleanup
    for d in tmpdirs:
        shutil.rmtree(d, ignore_errors=True)

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Result: {passed}/{total} tests passed")
    if passed == total:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
