"""In-memory Modbus register bank and optional static-register reload."""

from __future__ import annotations

import json
import os
import threading

from . import config, event_log

REG_LOCK = threading.Lock()
REGS: dict[int, int] = {}
REGISTER_FILE = config.DEFAULT_REGISTER_FILE
REGISTER_FILE_MTIME: float | None = None


# --- Register file hot-reload ---


def load_register_file_if_changed() -> None:
    """Load ``registers.json`` when its modification time changes."""
    global REGISTER_FILE_MTIME

    try:
        stat = os.stat(REGISTER_FILE)
    except FileNotFoundError:
        return
    except Exception as exc:
        event_log.log_event(
            "register_file_stat_error", path=REGISTER_FILE, error=str(exc)
        )
        return
    if REGISTER_FILE_MTIME == stat.st_mtime:
        return
    try:
        with open(REGISTER_FILE, "r", encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, dict):
            raise ValueError("registers.json must be a JSON object")
        new_regs: dict[int, int] = {}
        for key, value in raw.items():
            new_regs[int(key)] = int(value) & 0xFFFF
        with REG_LOCK:
            REGS.update(new_regs)
        REGISTER_FILE_MTIME = stat.st_mtime
        event_log.log_event(
            "register_file_loaded", path=REGISTER_FILE, count=len(new_regs)
        )
    except Exception as exc:
        event_log.log_event(
            "register_file_load_error", path=REGISTER_FILE, error=str(exc)
        )


def to_u32_pair(value: int) -> tuple[int, int]:
    """Split a 32-bit unsigned integer into high- and low-word values."""
    value = max(0, value) & 0xFFFFFFFF
    return (value >> 16) & 0xFFFF, value & 0xFFFF


def to_s32_pair(value: int) -> tuple[int, int]:
    """Split a signed 32-bit integer into two's-complement word values."""
    if value < 0:
        value += 0x100000000
    value &= 0xFFFFFFFF
    return (value >> 16) & 0xFFFF, value & 0xFFFF


def get_register(addr: int) -> int:
    """Return a register word, reloading static values when needed."""
    load_register_file_if_changed()
    with REG_LOCK:
        return REGS.get(addr, 0) & 0xFFFF


def set_register(addr: int, value: int) -> None:
    """Set a register word in the in-memory bank."""
    with REG_LOCK:
        REGS[addr] = value & 0xFFFF


def reset() -> None:
    """Clear the register bank and reload marker for an isolated test run."""
    global REGISTER_FILE_MTIME

    with REG_LOCK:
        REGS.clear()
        REGISTER_FILE_MTIME = None
