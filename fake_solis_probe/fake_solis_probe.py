#!/usr/bin/env python3
"""Fake Solis Probe for Home Assistant OS — v0.4.0.

Emulates a Solis S6-EH1P hybrid inverter via Modbus TCP on port 502.
Reads real PV data from configurable Home Assistant sensors via Supervisor API
and serves it to Tibber Bridge. Battery registers return safe zero values.
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import os
import socketserver
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

CONFIG_PATH = "/data/options.json"
EVENT_DIR = "/share/fake_solis_probe"
EVENT_LOG = os.path.join(EVENT_DIR, "events.jsonl")
REGISTER_FILE = os.path.join(EVENT_DIR, "registers.json")

VERSION = "0.4.0"

DEFAULT_OPTIONS: Dict[str, Any] = {
    "enable_http": False,
    "log_raw_hex": False,
    "mirror_writes": False,
    "ha_sensor_pv_power": "",
    "ha_sensor_grid_power": "",
    "ha_sensor_total_energy": "",
    "ha_sensor_daily_energy": "",
    "grid_power_sign_convention": "negate",
    "pv_power_scale": 1.0,
    "grid_power_scale": 1.0,
    "total_energy_scale": 10.0,
    "daily_energy_scale": 10.0,
    "fake_vendor": "Ginlong",
    "fake_inverter_model": "Solis S6-EH1P",
    "fake_logger_model": "S2-WL-ST",
    "fake_serial": "S2WLSTFAKE001",
}

# Sensor config keys (mapped to register blocks)
SENSOR_KEYS = [
    "ha_sensor_pv_power",
    "ha_sensor_grid_power",
    "ha_sensor_total_energy",
    "ha_sensor_daily_energy",
]

# Cache for HA sensor values (updated by background thread)
SENSOR_CACHE: Dict[str, Optional[float]] = {}
CACHE_LOCK = threading.Lock()

# Error backoff tracking: entity_id -> consecutive_error_count
SENSOR_ERROR_COUNT: Dict[str, int] = {}
ERROR_LOG_INTERVAL = 12  # Only log errors every 12th consecutive failure (~60s)

LOG_LOCK = threading.Lock()
REG_LOCK = threading.Lock()
REGS: Dict[int, int] = {}
REGISTER_FILE_MTIME: Optional[float] = None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_options() -> Dict[str, Any]:
    options = dict(DEFAULT_OPTIONS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            options.update(loaded)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[Fake Solis Probe] Failed to read {CONFIG_PATH}: {exc}", flush=True)
    return options


OPTIONS = load_options()


def log_event(kind: str, **data: Any) -> None:
    record = {"ts": now_iso(), "kind": kind, **data}
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
    with LOG_LOCK:
        print(line, flush=True)
        try:
            os.makedirs(EVENT_DIR, exist_ok=True)
            with open(EVENT_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            print(f"[Fake Solis Probe] Could not write {EVENT_LOG}: {exc}", flush=True)


def hex_bytes(data: bytes) -> str:
    return data.hex(" ")


# --- Startup validation ---

def ha_api_check_entity(entity_id: str) -> Tuple[bool, str]:
    """Check if an entity exists in HA. Returns (ok, message)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False, "SUPERVISOR_TOKEN not set"
    url = f"http://supervisor/core/api/states/{urllib.parse.quote(entity_id, safe='._-')}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        state = data.get("state", "") if isinstance(data, dict) else ""
        unit = ""
        if isinstance(data, dict) and isinstance(data.get("attributes"), dict):
            unit = data["attributes"].get("unit_of_measurement", "")
        return True, f"state={state}, unit={unit}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, f"Entity not found (404)"
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def validate_config() -> bool:
    """Validate all required config options at startup. Returns True if OK."""
    errors: List[str] = []

    # Check sensor entity IDs are non-empty
    sensor_map = {}
    for key in SENSOR_KEYS:
        entity_id = str(OPTIONS.get(key, "")).strip()
        if not entity_id:
            errors.append(f"Option '{key}' is empty — must be a valid HA entity ID")
        elif not entity_id.startswith("sensor."):
            errors.append(f"Option '{key}' = '{entity_id}' — expected entity starting with 'sensor.'")
        else:
            sensor_map[key] = entity_id

    # Check grid_power_sign_convention
    sign_conv = str(OPTIONS.get("grid_power_sign_convention", "")).strip()
    if sign_conv not in ("negate", "direct"):
        errors.append(
            f"Option 'grid_power_sign_convention' = '{sign_conv}' — must be 'negate' or 'direct'"
        )

    # Check scaling factors are positive numbers
    for scale_key in ("pv_power_scale", "grid_power_scale", "total_energy_scale", "daily_energy_scale"):
        try:
            val = float(OPTIONS.get(scale_key, 0))
            if val <= 0:
                errors.append(f"Option '{scale_key}' = {val} — must be > 0")
        except (ValueError, TypeError):
            errors.append(f"Option '{scale_key}' = '{OPTIONS.get(scale_key)}' — must be a number")

    # If basic validation passed, verify entities exist in HA
    if not errors:
        log_event("config_validating_entities", entities=sensor_map)
        for key, entity_id in sensor_map.items():
            ok, msg = ha_api_check_entity(entity_id)
            if ok:
                log_event("config_entity_ok", key=key, entity_id=entity_id, detail=msg)
            else:
                errors.append(f"Option '{key}' = '{entity_id}' — entity not found in HA: {msg}")

    if errors:
        log_event("config_validation_failed", errors=errors)
        for err in errors:
            print(f"[FATAL] {err}", flush=True)
        return False

    log_event("config_validation_passed", sensors=sensor_map, sign_convention=sign_conv)
    return True


# --- Register file hot-reload ---

def load_register_file_if_changed() -> None:
    global REGISTER_FILE_MTIME
    try:
        stat = os.stat(REGISTER_FILE)
    except FileNotFoundError:
        return
    except Exception as exc:
        log_event("register_file_stat_error", path=REGISTER_FILE, error=str(exc))
        return
    if REGISTER_FILE_MTIME == stat.st_mtime:
        return
    try:
        with open(REGISTER_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("registers.json must be a JSON object")
        new_regs: Dict[int, int] = {}
        for key, value in raw.items():
            new_regs[int(key)] = int(value) & 0xFFFF
        with REG_LOCK:
            REGS.update(new_regs)
        REGISTER_FILE_MTIME = stat.st_mtime
        log_event("register_file_loaded", path=REGISTER_FILE, count=len(new_regs))
    except Exception as exc:
        log_event("register_file_load_error", path=REGISTER_FILE, error=str(exc))


# --- HA Sensor → Modbus register mapping ---

def _to_u32_pair(value: int) -> Tuple[int, int]:
    """Split a 32-bit unsigned int into (high_word, low_word)."""
    value = max(0, value) & 0xFFFFFFFF
    return (value >> 16) & 0xFFFF, value & 0xFFFF

def _to_s32_pair(value: int) -> Tuple[int, int]:
    """Split a 32-bit signed int into (high_word, low_word). Two's complement."""
    if value < 0:
        value = value + 0x100000000
    value = value & 0xFFFFFFFF
    return (value >> 16) & 0xFFFF, value & 0xFFFF

def update_live_registers() -> None:
    """Push cached HA sensor values into the Modbus register map."""
    pv_entity = str(OPTIONS.get("ha_sensor_pv_power", ""))
    grid_entity = str(OPTIONS.get("ha_sensor_grid_power", ""))
    total_entity = str(OPTIONS.get("ha_sensor_total_energy", ""))
    daily_entity = str(OPTIONS.get("ha_sensor_daily_energy", ""))

    sign_conv = str(OPTIONS.get("grid_power_sign_convention", "negate"))
    pv_scale = float(OPTIONS.get("pv_power_scale", 1.0))
    grid_scale = float(OPTIONS.get("grid_power_scale", 1.0))
    total_scale = float(OPTIONS.get("total_energy_scale", 10.0))
    daily_scale = float(OPTIONS.get("daily_energy_scale", 10.0))

    with CACHE_LOCK:
        pv_raw = SENSOR_CACHE.get(pv_entity)
        grid_raw = SENSOR_CACHE.get(grid_entity)
        total_raw = SENSOR_CACHE.get(total_entity)
        daily_raw = SENSOR_CACHE.get(daily_entity)

    with REG_LOCK:
        # 33057-33058: PV Active Power (U32, W)
        if pv_raw is not None:
            hi, lo = _to_u32_pair(int(pv_raw * pv_scale))
            REGS[33057] = hi
            REGS[33058] = lo

        # 33263-33264: Grid Import/Export Power (S32, W)
        if grid_raw is not None:
            grid_w = int(grid_raw * grid_scale)
            if sign_conv == "negate":
                grid_w = -grid_w
            hi, lo = _to_s32_pair(grid_w)
            REGS[33263] = hi
            REGS[33264] = lo

        # 34391-34393: Total Energy (U32 in scaled units + trailing U16)
        if total_raw is not None:
            hi, lo = _to_u32_pair(int(total_raw * total_scale))
            REGS[34391] = hi
            REGS[34392] = lo
            REGS[34393] = 0

        # 34621-34622: Daily Energy (U32 in scaled units)
        if daily_raw is not None:
            hi, lo = _to_u32_pair(int(daily_raw * daily_scale))
            REGS[34621] = hi
            REGS[34622] = lo

        # Battery registers — always zero (no battery)
        REGS[33121] = 0
        REGS[33245] = 0
        REGS[34351] = 0
        for addr in range(33135, 33152):
            REGS[addr] = 0


def get_reg(addr: int) -> int:
    load_register_file_if_changed()
    with REG_LOCK:
        return REGS.get(addr, 0) & 0xFFFF


def set_reg(addr: int, value: int) -> None:
    with REG_LOCK:
        REGS[addr] = value & 0xFFFF


def exception_pdu(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


def device_id_objects() -> List[Tuple[int, bytes]]:
    vendor = str(OPTIONS.get("fake_vendor", "Ginlong"))
    model = str(OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
    serial = str(OPTIONS.get("fake_serial", "S2WLSTFAKE001"))
    logger_model = str(OPTIONS.get("fake_logger_model", "S2-WL-ST"))
    return [
        (0x00, vendor.encode("ascii", "ignore")),
        (0x01, model.encode("ascii", "ignore")),
        (0x02, b"1.00"),
        (0x03, serial.encode("ascii", "ignore")),
        (0x04, logger_model.encode("ascii", "ignore")),
    ]


# --- Modbus TCP Server ---

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ModbusHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer_ip, peer_port = self.client_address[:2]
        log_event("modbus_connection_open", peer_ip=peer_ip, peer_port=peer_port)
        try:
            while True:
                header = self._recv_exact(7)
                if header is None:
                    return
                tid, proto, length, uid = struct.unpack(">HHHB", header)
                if length < 1 or length > 260:
                    log_event("modbus_bad_mbap_length", peer_ip=peer_ip,
                              transaction_id=tid, length=length)
                    return
                pdu = self._recv_exact(length - 1)
                if pdu is None:
                    return
                if not pdu:
                    continue
                fc = pdu[0]
                if OPTIONS.get("log_raw_hex", False):
                    log_event("modbus_request_raw", peer_ip=peer_ip,
                              transaction_id=tid, protocol_id=proto,
                              unit_id=uid, length=length, pdu_hex=hex_bytes(pdu))
                try:
                    resp_pdu = self.process_pdu(peer_ip, uid, fc, pdu)
                except Exception as exc:
                    log_event("modbus_process_error", peer_ip=peer_ip,
                              unit_id=uid, fc=fc, error=str(exc))
                    resp_pdu = exception_pdu(fc, 4)
                resp_hdr = struct.pack(">HHHB", tid, 0, len(resp_pdu) + 1, uid)
                self.request.sendall(resp_hdr + resp_pdu)
                if OPTIONS.get("log_raw_hex", False):
                    log_event("modbus_response_raw", peer_ip=peer_ip,
                              transaction_id=tid, unit_id=uid,
                              pdu_hex=hex_bytes(resp_pdu))
        except ConnectionResetError:
            log_event("modbus_connection_reset", peer_ip=peer_ip, peer_port=peer_port)
        except Exception as exc:
            log_event("modbus_connection_error", peer_ip=peer_ip,
                      peer_port=peer_port, error=str(exc))
        finally:
            log_event("modbus_connection_close", peer_ip=peer_ip, peer_port=peer_port)

    def _recv_exact(self, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None if not buf else None
            buf += chunk
        return buf

    def process_pdu(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        if fc in (1, 2):
            return self._read_bits(peer_ip, uid, fc, pdu)
        if fc in (3, 4):
            return self._read_registers(peer_ip, uid, fc, pdu)
        if fc == 5:
            return self._write_single_coil(peer_ip, uid, pdu)
        if fc == 6:
            return self._write_single_register(peer_ip, uid, pdu)
        if fc == 8:
            return pdu  # diagnostics echo
        if fc == 15:
            return self._write_multiple_coils(peer_ip, uid, pdu)
        if fc == 16:
            return self._write_multiple_registers(peer_ip, uid, pdu)
        if fc == 17:
            return self._report_server_id(peer_ip, uid)
        if fc == 43:
            return self._read_device_id(peer_ip, uid, pdu)
        log_event("modbus_unsupported_function", peer_ip=peer_ip, fc=fc)
        return exception_pdu(fc, 1)

    def _read_bits(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(fc, 3)
        start, qty = struct.unpack(">HH", pdu[1:5])
        log_event("modbus_read_bits", peer_ip=peer_ip, fc=fc, unit_id=uid,
                  start=start, qty=qty)
        if qty < 1 or qty > 2000:
            return exception_pdu(fc, 3)
        bc = (qty + 7) // 8
        return bytes([fc, bc]) + bytes(bc)

    def _read_registers(self, peer_ip: str, uid: int, fc: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(fc, 3)
        start, qty = struct.unpack(">HH", pdu[1:5])
        log_event("modbus_read_registers", peer_ip=peer_ip, fc=fc, unit_id=uid,
                  start=start, qty=qty, end=start + qty - 1)
        if qty < 1 or qty > 125:
            return exception_pdu(fc, 3)
        data = b"".join(struct.pack(">H", get_reg(start + i)) for i in range(qty))
        return bytes([fc, len(data)]) + data

    def _write_single_coil(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(5, 3)
        addr, val = struct.unpack(">HH", pdu[1:5])
        log_event("modbus_write_single_coil", peer_ip=peer_ip, addr=addr, value=val)
        return pdu[:5]

    def _write_single_register(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 5:
            return exception_pdu(6, 3)
        addr, val = struct.unpack(">HH", pdu[1:5])
        mirrored = bool(OPTIONS.get("mirror_writes", False))
        log_event("modbus_write_single_register", peer_ip=peer_ip,
                  addr=addr, value=val, mirrored=mirrored)
        if mirrored:
            set_reg(addr, val)
        return pdu[:5]

    def _write_multiple_coils(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(15, 3)
        addr, qty, bc = struct.unpack(">HHB", pdu[1:6])
        log_event("modbus_write_multiple_coils", peer_ip=peer_ip,
                  addr=addr, qty=qty)
        return bytes([15]) + struct.pack(">HH", addr, qty)

    def _write_multiple_registers(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(16, 3)
        addr, qty, bc = struct.unpack(">HHB", pdu[1:6])
        raw = pdu[6:6 + bc]
        values = []
        for i in range(0, len(raw), 2):
            if i + 1 < len(raw):
                values.append(struct.unpack(">H", raw[i:i+2])[0])
        mirrored = bool(OPTIONS.get("mirror_writes", False))
        log_event("modbus_write_multiple_registers", peer_ip=peer_ip,
                  addr=addr, qty=qty, values=values, mirrored=mirrored)
        if mirrored:
            for off, v in enumerate(values[:qty]):
                set_reg(addr + off, v)
        return bytes([16]) + struct.pack(">HH", addr, qty)

    def _report_server_id(self, peer_ip: str, uid: int) -> bytes:
        vendor = str(OPTIONS.get("fake_vendor", "Ginlong"))
        model = str(OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
        text = f"{vendor} Solis {model}".encode("ascii", "ignore")[:240]
        payload = b"\x01\xff" + text
        log_event("modbus_report_server_id", peer_ip=peer_ip)
        return bytes([17, len(payload)]) + payload

    def _read_device_id(self, peer_ip: str, uid: int, pdu: bytes) -> bytes:
        if len(pdu) < 4 or pdu[1] != 0x0E:
            return exception_pdu(43, 1)
        code = pdu[2]
        obj_id = pdu[3]
        objs = device_id_objects()
        if code == 4:
            sel = [(o, v) for o, v in objs if o == obj_id]
        else:
            sel = [(o, v) for o, v in objs if o >= obj_id]
        sel = sel[:5]
        body = bytearray([0x2B, 0x0E, code, 0x03, 0x00, 0x00, len(sel)])
        for oid, val in sel:
            val = val[:240]
            body.extend([oid, len(val)])
            body.extend(val)
        log_event("modbus_read_device_id", peer_ip=peer_ip,
                  objects=[o for o, _ in sel])
        return bytes(body)


# --- HTTP Probe (disabled by default) ---

class ProbeHTTPHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SolisDataLogger/1.0"
    sys_version = ""

    def do_GET(self): self._handle(True)
    def do_POST(self): self._handle(True)
    def do_HEAD(self): self._handle(False)
    def log_message(self, *a): pass

    def _handle(self, send_body: bool) -> None:
        log_event("http_request", peer_ip=self.client_address[0],
                  method=self.command, path=self.path)
        payload = json.dumps({"vendor": "Ginlong", "model": "S6-EH1P",
                              "status": "online"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)


# --- HA Supervisor API sensor polling ---

def ha_api_get_state(entity_id: str) -> Optional[float]:
    """Read a sensor state from HA Core API. Returns float or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    url = f"http://supervisor/core/api/states/{urllib.parse.quote(entity_id, safe='._-')}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        state = data.get("state") if isinstance(data, dict) else None
        if state in (None, "unavailable", "unknown", ""):
            return None
        return float(state)
    except (ValueError, TypeError):
        return None
    except Exception as exc:
        # Don't log here — caller handles backoff logging
        return None


def sensor_poll_loop() -> None:
    """Background thread: poll HA sensors every 5 seconds, update registers."""
    entity_ids = [
        str(OPTIONS.get(key, "")) for key in SENSOR_KEYS
    ]
    entity_ids = [e for e in entity_ids if e]

    # Initialize cache
    with CACHE_LOCK:
        for eid in entity_ids:
            if eid not in SENSOR_CACHE:
                SENSOR_CACHE[eid] = None

    log_event("sensor_poll_started", sensors=entity_ids)
    poll_counter = 0

    while True:
        for entity_id in entity_ids:
            val = ha_api_get_state(entity_id)

            if val is not None:
                # Success — update cache and reset error count
                with CACHE_LOCK:
                    SENSOR_CACHE[entity_id] = val
                SENSOR_ERROR_COUNT[entity_id] = 0
            else:
                # Failed — keep last known value, log with backoff
                count = SENSOR_ERROR_COUNT.get(entity_id, 0) + 1
                SENSOR_ERROR_COUNT[entity_id] = count
                if count == 1 or count % ERROR_LOG_INTERVAL == 0:
                    with CACHE_LOCK:
                        last = SENSOR_CACHE.get(entity_id)
                    log_event("sensor_unavailable", entity_id=entity_id,
                              consecutive_errors=count,
                              using_last_value=last)
                # Don't update cache — keeps last known value (or None if never read)

        update_live_registers()

        # Log current values periodically (every ~60s = 12 cycles)
        poll_counter += 1
        if poll_counter % 12 == 1:
            with CACHE_LOCK:
                snapshot = dict(SENSOR_CACHE)
            log_event("sensor_poll_values", values=snapshot)

        time.sleep(5)


# --- Main ---

def serve_http() -> None:
    try:
        log_event("http_server_starting", port=80)
        with ThreadedTCPServer(("0.0.0.0", 80), ProbeHTTPHandler) as srv:
            log_event("http_server_started", port=80)
            srv.serve_forever()
    except Exception as exc:
        log_event("http_server_failed", error=str(exc))


def serve_modbus() -> None:
    log_event("modbus_server_starting", host="0.0.0.0", port=502)
    with ThreadedTCPServer(("0.0.0.0", 502), ModbusHandler) as srv:
        log_event("modbus_server_started", host="0.0.0.0", port=502)
        srv.serve_forever()


def main() -> int:
    os.makedirs(EVENT_DIR, exist_ok=True)
    log_event("probe_start", version=VERSION, options={k: v for k, v in OPTIONS.items()})
    load_register_file_if_changed()

    # Validate configuration before starting
    if not validate_config():
        log_event("probe_exit", reason="config_validation_failed")
        return 1

    # Start HA sensor polling thread
    threading.Thread(target=sensor_poll_loop, name="sensor-poll",
                     daemon=True).start()

    if bool(OPTIONS.get("enable_http", False)):
        threading.Thread(target=serve_http, name="http", daemon=True).start()
    else:
        log_event("http_server_disabled")

    try:
        serve_modbus()
    except Exception as exc:
        log_event("modbus_server_failed", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
