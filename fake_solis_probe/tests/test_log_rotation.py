"""Log rotation tests

Tests rotate_log_if_needed() using a real temporary directory and real file I/O,
so os.path.getsize, os.replace, and os.path.exists exercise actual disk behaviour.

Run with pytest:
    python -m pytest fake_solis_probe/tests/test_log_rotation.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solis_probe import config, event_log


# ---------------------------------------------------------------------------
# Fixtures and helpers use real temporary paths, not a stubbed filesystem.
# ---------------------------------------------------------------------------


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the real logger at an isolated temporary event log."""
    path = tmp_path / "events.jsonl"
    config.configure_options()
    monkeypatch.setattr(event_log, "EVENT_DIR", str(tmp_path))
    monkeypatch.setattr(event_log, "EVENT_LOG", str(path))
    return path


def configure_rotation(max_bytes: int, backup_count: int) -> None:
    """Set the two rotation options for one test case."""
    config.OPTIONS["log_max_bytes"] = max_bytes
    config.OPTIONS["log_backup_count"] = backup_count


def write_bytes(path: Path, size: int) -> None:
    """Write ``size`` bytes of dummy content to ``path``."""
    path.write_bytes(b"x" * size)


def test_initialize_log_creates_the_directory_and_log_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup owns the event-log path instead of delegating it to run.sh."""
    path = tmp_path / "nested" / "events.jsonl"
    config.configure_options()
    monkeypatch.setattr(event_log, "EVENT_DIR", str(path.parent))
    monkeypatch.setattr(event_log, "EVENT_LOG", str(path))

    event_log.initialize_log()

    assert path.parent.is_dir()
    assert path.is_file()


@pytest.mark.parametrize(
    ("max_bytes", "payload_size"),
    [
        pytest.param(100, 99, id="below-threshold"),
        pytest.param(0, 200, id="rotation-disabled"),
    ],
)
def test_rotation_is_skipped_when_not_required(
    log_path: Path,
    max_bytes: int,
    payload_size: int,
) -> None:
    """Below threshold must not rotate; log_max_bytes=0 leaves a large log untouched."""
    configure_rotation(max_bytes, 3)
    write_bytes(log_path, payload_size)

    event_log.rotate_log_if_needed()

    assert log_path.exists()
    assert log_path.stat().st_size == payload_size
    assert not log_path.with_name("events.jsonl.1").exists()


@pytest.mark.parametrize(
    "payload_size",
    [
        pytest.param(100, id="at-threshold"),
        pytest.param(200, id="above-threshold"),
    ],
)
def test_rotation_moves_current_log_to_first_backup(
    log_path: Path,
    payload_size: int,
) -> None:
    """A file at or above the threshold is renamed to .1."""
    configure_rotation(100, 3)
    write_bytes(log_path, payload_size)

    event_log.rotate_log_if_needed()

    first_backup = log_path.with_name("events.jsonl.1")
    assert not log_path.exists()
    assert first_backup.stat().st_size == payload_size


@pytest.mark.parametrize(
    ("backup_count", "expected_sizes"),
    [
        pytest.param(2, (200, 150), id="limited-backups"),
        pytest.param(3, (200, 150, 120), id="cascade-all-backups"),
    ],
)
def test_rotation_cascades_existing_backups(
    log_path: Path,
    backup_count: int,
    expected_sizes: tuple[int, ...],
) -> None:
    """Cascade: .2 → .3, .1 → .2, current → .1.

    With backup_count=2, .1 shifts to .2 and overwrites the oldest .2; no .3
    backup is retained.
    """
    configure_rotation(100, backup_count)
    # Pre-create existing backups with distinct sizes so we can track them.
    write_bytes(log_path, 200)
    write_bytes(log_path.with_name("events.jsonl.1"), 150)
    write_bytes(log_path.with_name("events.jsonl.2"), 120)

    event_log.rotate_log_if_needed()

    assert not log_path.exists()
    for number, expected_size in enumerate(expected_sizes, start=1):
        assert (
            log_path.with_name(f"events.jsonl.{number}").stat().st_size == expected_size
        )
    assert not log_path.with_name(f"events.jsonl.{backup_count + 1}").exists()


@pytest.mark.parametrize(
    "backup_count",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
def test_nonpositive_backup_counts_truncate_in_place(
    log_path: Path,
    backup_count: int,
) -> None:
    """Zero and negative backup counts truncate in place with no .1 backup.

    For a negative backup count, this guards the regression where the value
    bypassed the zero-only truncate branch and fell through to renaming
    events.jsonl to events.jsonl.1.
    """
    configure_rotation(100, backup_count)
    write_bytes(log_path, 200)

    event_log.rotate_log_if_needed()

    assert log_path.exists()
    assert log_path.stat().st_size == 0
    assert not log_path.with_name("events.jsonl.1").exists()


def test_missing_log_file_does_not_raise_or_create_a_backup(log_path: Path) -> None:
    """If events.jsonl does not exist yet, rotation must not raise."""
    configure_rotation(100, 3)

    # Do NOT create the file.
    event_log.rotate_log_if_needed()

    assert not log_path.exists()
    assert not log_path.with_name("events.jsonl.1").exists()


def test_log_event_rotates_then_writes_the_new_event(log_path: Path) -> None:
    """Verify log rotation fires through the same path log_event() uses."""
    configure_rotation(200, 2)
    # Pre-fill the file to above the threshold.
    write_bytes(log_path, 250)

    # log_event() rotates first, then appends the new event.
    event_log.log_event("test_event")

    assert log_path.with_name("events.jsonl.1").stat().st_size == 250
    assert '"kind":"test_event"' in log_path.read_text(encoding="utf-8")
