# Architecture

## Overview

This addon creates a bridge between a real Solis string inverter (via Home Assistant sensors)
and Tibber Bridge, by emulating a Solis S6-EH1P hybrid inverter over Modbus TCP.

## Full Data Chain

```
Real Solis 5P inverter (DC strings → AC grid)
  └─ RS485 → S2-WL-ST datalogger (Solis WiFi stick)
       └─ Modbus TCP → solis_modbus HACS integration
            └─ Home Assistant entities (sensor.*)
                 └─ HA Supervisor API (http://supervisor/core/api/states/...)
                      └─ Fake Solis Probe addon (this project)
                           └─ Modbus TCP server :502 (emulates S6-EH1P)
                                └─ Tibber Bridge (LAN discovery + polling)
                                     └─ Tibber Cloud
                                          └─ Tibber mobile app
```

The addon **never communicates with the real inverter or datalogger**. It only reads
from HA's internal state machine via the Supervisor API.

## Why Port 502 on the HA IP?

Tibber Bridge discovers inverters by scanning the local LAN for open port 502 (standard
Modbus TCP port). It then reads a type register (35000) to identify the inverter model.

The addon binds to `0.0.0.0:502` inside its container. The HAOS network stack maps this
to the HA host IP on the same LAN segment, making it visible to Tibber Bridge.

**Why not macvlan / separate IP?**
macvlan would require network configuration outside the addon scope. Port 502 on the HA
host IP works reliably with the standard HAOS networking model.

**Why not port 1502?**
Tibber Bridge scans specifically for port 502. There is no known configuration option
to change this in the Tibber Bridge firmware.

## Modbus Function Codes Handled

| FC | Name | Behavior |
|---|---|---|
| 1, 2 | Read Coils / Discrete Inputs | Returns all-zero bytes (required, observed in initial handshake) |
| 3 | Read Holding Registers | Returns 0 for all addresses (Tibber reads a few config registers once) |
| 4 | Read Input Registers | **Primary data path** — returns live PV data and battery stub |
| 5 | Write Single Coil | Logged, not applied (no writes observed from Tibber in practice) |
| 6 | Write Single Register | Logged; applied only if `mirror_writes: true` |
| 8 | Diagnostics | Echo (required by Modbus spec) |
| 15 | Write Multiple Coils | Logged, acknowledged, not applied |
| 16 | Write Multiple Registers | Logged; applied only if `mirror_writes: true` |
| 17 | Report Server ID | Returns vendor/model string |
| 43 | Read Device Identification | Returns vendor, model, version, serial, logger model |

## HA Supervisor API Integration

The addon uses `homeassistant_api: true` in `config.yaml`, which:

1. Gives the addon access to the internal Supervisor HTTP API
2. Injects the `SUPERVISOR_TOKEN` environment variable at runtime

The addon polls `http://supervisor/core/api/states/<entity_id>` every 5 seconds for each
configured sensor. This is the standard HAOS mechanism — no tokens are hardcoded.

## Security Design

- **No writes forwarded**: Modbus writes from Tibber are logged but never applied to any
  real device. `mirror_writes: false` is the default.
- **Read-only data**: The addon only exposes PV production data — no credentials, no
  inverter control registers.
- **LAN-only**: The Modbus server binds to `0.0.0.0:502` inside the container, which is
  only reachable from the local LAN. It is not exposed to the internet.
- **Token isolation**: `SUPERVISOR_TOKEN` is injected by HAOS and scoped to the addon.
  It is never logged or stored.

## Scaling and Unit Conversion

Solis hybrid inverters report energy in 0.1 kWh units (i.e. the raw register value is
`kWh × 10`). Power registers are in Watts, direct.

The configurable scale factors allow adaptation for sensors that report in different units:

| Scenario | Scale |
|---|---|
| Power sensor in W (standard) | 1.0 |
| Power sensor in kW | 1000.0 |
| Energy sensor in kWh → 0.1 kWh register | 10.0 |
| Energy sensor in Wh → 0.1 kWh register | 0.01 |

## Grid Power Sign Convention

Register 33263–33264 is a signed S32 (two's complement, big-endian, HI word first):

- **Positive** = exporting to grid
- **Negative** = importing from grid

Most net-meter sensors (Tibber Pulse, smart meters, HA energy integrations) use the
**opposite** convention: positive = import. Use `grid_power_sign_convention: negate` in
that case. If your sensor already uses the Solis convention, use `direct`.

## Threading Model

```
main thread:     Modbus TCP server (blocking serve_forever)
sensor-poll:     Background daemon thread, 5-second poll loop
http (optional): Background daemon thread for HTTP probe
```

The Modbus server is multi-threaded (one thread per client connection via `ThreadingMixIn`).
The `SENSOR_CACHE` dict is protected by `CACHE_LOCK`, and `REGS` by `REG_LOCK`.
