"""Application composition and server lifecycle for Fake Solis Probe."""

from __future__ import annotations

import socketserver
import threading

from . import (
    config,
    event_log,
    http_probe,
    modbus,
    polling,
    registers,
    validation,
)


VERSION = "0.7.0"


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Thread-per-connection TCP server used for Modbus and optional HTTP."""

    allow_reuse_address = True
    daemon_threads = True


def serve_http() -> None:
    """Run the optional HTTP discovery probe."""
    try:
        event_log.log_event("http_server_starting", port=80)
        with ThreadedTCPServer(("0.0.0.0", 80), http_probe.ProbeHTTPHandler) as server:
            event_log.log_event("http_server_started", port=80)
            server.serve_forever()
    except Exception as exc:
        event_log.log_event("http_server_failed", error=str(exc))


def serve_modbus() -> None:
    """Run the Modbus TCP server until it stops or raises."""
    event_log.log_event("modbus_server_starting", host="0.0.0.0", port=502)
    with ThreadedTCPServer(("0.0.0.0", 502), modbus.ModbusHandler) as server:
        event_log.log_event("modbus_server_started", host="0.0.0.0", port=502)
        server.serve_forever()


def main() -> int:
    """Load options, validate startup state, and run the Modbus service."""
    config.load_runtime_options()
    event_log.initialize_log()
    event_log.log_event(
        "probe_start",
        version=VERSION,
        options={key: value for key, value in config.OPTIONS.items()},
    )
    registers.load_register_file_if_changed()

    # Write inverter type code from config into register 35000. This runs after
    # load_register_file_if_changed(), so the config option takes priority over
    # any "35000" key in registers.json at startup. Runtime hot reload via
    # get_register() can override it if that file contains "35000".
    type_code = int(config.OPTIONS.get("fake_inverter_type_code", 2030))
    with registers.REG_LOCK:
        registers.REGS[35000] = type_code & 0xFFFF
    event_log.log_event("inverter_type_code_set", register=35000, value=type_code)

    # Validate configuration before starting.
    if not validation.validate_config():
        event_log.log_event("probe_exit", reason="config_validation_failed")
        return 1

    # Start HA sensor polling thread.
    threading.Thread(
        target=polling.sensor_poll_loop,
        name="sensor-poll",
        daemon=True,
    ).start()

    if bool(config.OPTIONS.get("enable_http", False)):
        threading.Thread(target=serve_http, name="http", daemon=True).start()
    else:
        event_log.log_event("http_server_disabled")

    try:
        serve_modbus()
    except Exception as exc:
        event_log.log_event("modbus_server_failed", error=str(exc))
        return 1
    return 0
