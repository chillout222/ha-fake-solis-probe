"""Static settings and Home Assistant App option loading."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping


CONFIG_PATH = "/data/options.json"
DEFAULT_EVENT_DIR = "/share/fake_solis_probe"
DEFAULT_EVENT_LOG = os.path.join(DEFAULT_EVENT_DIR, "events.jsonl")
DEFAULT_REGISTER_FILE = os.path.join(DEFAULT_EVENT_DIR, "registers.json")

# Kept as aliases for callers that need the canonical runtime paths.
EVENT_DIR = DEFAULT_EVENT_DIR
EVENT_LOG = DEFAULT_EVENT_LOG
REGISTER_FILE = DEFAULT_REGISTER_FILE

# Only log repeated sensor and fallback errors every 12th failure (~60 seconds).
ERROR_LOG_INTERVAL = 12

DEFAULT_OPTIONS: dict[str, Any] = {
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
    "pv_power_unavailable_behavior": "zero",
    "grid_power_unavailable_behavior": "zero",
    "total_energy_unavailable_behavior": "last_known",
    "daily_energy_unavailable_behavior": "zero",
    "fake_vendor": "Ginlong",
    "fake_inverter_model": "Solis S6-EH1P",
    "fake_logger_model": "S2-WL-ST",
    "fake_serial": "S2WLSTFAKE001",
    "fake_inverter_type_code": 2030,
    # Log rotation (v0.7.0)
    "log_max_bytes": 5 * 1024 * 1024,  # 5 MB — rotate when file exceeds this
    "log_backup_count": 3,  # number of .1/.2/.3 backups to keep
}

# Sensor config keys (mapped to register blocks)
SENSOR_KEYS = [
    "ha_sensor_pv_power",
    "ha_sensor_grid_power",
    "ha_sensor_total_energy",
    "ha_sensor_daily_energy",
]

# Importing a module must be safe for tests and tooling. App startup calls
# load_runtime_options() exactly once after its runtime environment is ready.
OPTIONS: dict[str, Any] = dict(DEFAULT_OPTIONS)


def load_options(path: str = CONFIG_PATH) -> dict[str, Any]:
    """Return defaults overlaid with the App options stored at *path*."""
    options = dict(DEFAULT_OPTIONS)
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            loaded = json.load(file_handle)
        if isinstance(loaded, dict):
            options.update(loaded)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[Fake Solis Probe] Failed to read {path}: {exc}", flush=True)
    return options


def configure_options(options: Mapping[str, Any] | None = None) -> None:
    """Reset runtime options to defaults and overlay an optional mapping.

    The dictionary is mutated in place so modules that imported ``OPTIONS``
    retain the current configuration without being reloaded.
    """
    OPTIONS.clear()
    OPTIONS.update(DEFAULT_OPTIONS)
    if options is not None:
        OPTIONS.update(options)


def load_runtime_options() -> None:
    """Load App options into the shared runtime mapping at application startup."""
    configure_options(load_options())
