"""Structured runtime event logging with bounded on-disk retention."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from typing import Any

from . import config


EVENT_DIR = config.DEFAULT_EVENT_DIR
EVENT_LOG = config.DEFAULT_EVENT_LOG
LOG_LOCK = threading.Lock()


def initialize_log() -> None:
    """Create the event-log directory and ensure the JSONL file exists."""
    os.makedirs(EVENT_DIR, exist_ok=True)
    with open(EVENT_LOG, "a", encoding="utf-8"):
        pass


def now_iso() -> str:
    """Return the current local ISO-8601 timestamp with an explicit offset."""
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def rotate_log_if_needed() -> None:
    """Rotate ``events.jsonl`` if it exceeds ``log_max_bytes``.

    Must be called while ``LOG_LOCK`` is already held.

    Behaviour:
        log_max_bytes <= 0  → rotation disabled; return immediately.
        log_backup_count <= 0  → truncate in-place (no .1 backup kept).
        log_backup_count >= 1  → cascade rename:
            .N-1 → .N, …, .1 → .2, current → .1

    Rotation failures are printed to stdout but never raise, so ``log_event()``
    can always continue and attempt to append the new line.
    """
    max_bytes = int(config.OPTIONS.get("log_max_bytes", 5 * 1024 * 1024))
    backup_count = int(config.OPTIONS.get("log_backup_count", 3))
    if max_bytes <= 0:
        return  # rotation explicitly disabled
    try:
        size = os.path.getsize(EVENT_LOG)
    except FileNotFoundError:
        return  # file doesn't exist yet — nothing to rotate
    except Exception:
        return  # stat error — skip silently, don't crash
    if size < max_bytes:
        return  # still within threshold
    if backup_count <= 0:
        # Truncate in-place: open in write mode to clear, keep the same path.
        try:
            with open(EVENT_LOG, "w", encoding="utf-8"):
                pass  # opening in "w" mode truncates the file
            print(
                f"[Fake Solis Probe] log truncated: {EVENT_LOG}"
                f" ({size // 1024} KiB cleared, no backups kept)",
                flush=True,
            )
        except Exception as exc:
            print(f"[Fake Solis Probe] log truncation failed: {exc}", flush=True)
        return

    # Cascade existing backups upward (highest first to avoid clobbering).
    for number in range(backup_count - 1, 0, -1):
        source = f"{EVENT_LOG}.{number}"
        destination = f"{EVENT_LOG}.{number + 1}"
        try:
            if os.path.exists(source):
                os.replace(source, destination)
        except Exception as exc:
            print(
                f"[Fake Solis Probe] log rotation rename {source} -> {destination}: {exc}",
                flush=True,
            )

    # Move the current log to .1.
    try:
        os.replace(EVENT_LOG, f"{EVENT_LOG}.1")
        print(
            f"[Fake Solis Probe] log rotated: {EVENT_LOG}"
            f" ({size // 1024} KiB) -> .1  (backup_count={backup_count})",
            flush=True,
        )
    except Exception as exc:
        print(f"[Fake Solis Probe] log rotation rename to .1 failed: {exc}", flush=True)


def log_event(kind: str, **data: Any) -> None:
    """Print and append one compact JSON event, rotating first when needed."""
    record = {"ts": now_iso(), "kind": kind, **data}
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
    with LOG_LOCK:
        print(line, flush=True)
        try:
            initialize_log()
            rotate_log_if_needed()  # rotate before writing; failures are non-fatal
            with open(EVENT_LOG, "a", encoding="utf-8") as file_handle:
                file_handle.write(line + "\n")
        except Exception as exc:
            print(f"[Fake Solis Probe] Could not write {EVENT_LOG}: {exc}", flush=True)


def hex_bytes(data: bytes) -> str:
    """Return a space-separated lower-case hexadecimal byte string."""
    return data.hex(" ")
