# Fake Solis Probe — HAOS Addon

Emulates a **Solis S6-EH1P hybrid inverter** via Modbus TCP (port 502) so that
**Tibber Bridge** can read solar data from any PV system with Home Assistant sensors.

## Data Chain

```
Your PV inverter (any brand)
  └─ Home Assistant integration (Modbus, API, MQTT, etc.)
       └─ HA sensors (power, energy)
            └─ Fake Solis Probe addon (reads HA sensors via Supervisor API)
                 └─ Modbus TCP server :502 (emulates S6-EH1P hybrid)
                      └─ Tibber Bridge (polls every 10 seconds)
                           └─ Tibber Cloud → Tibber app
```

## Safety

- The addon **never** communicates with your real inverter hardware.
- No Modbus commands are forwarded to any physical device.
- Writes from Tibber Bridge are logged but **ignored** (`mirror_writes: false`).
- `SUPERVISOR_TOKEN` is used for HA Core API — no tokens are hardcoded.

## Configuration

After installing, go to **Configuration** tab and set your sensor entity IDs:

### Required sensor options

| Option | Description | Example |
|---|---|---|
| `ha_sensor_pv_power` | PV active power sensor (W) | `sensor.solis_active_power` |
| `ha_sensor_grid_power` | Net grid power sensor (W, signed) | `sensor.grid_net_power` |
| `ha_sensor_total_energy` | Lifetime total energy sensor (kWh) | `sensor.solis_total_energy` |
| `ha_sensor_daily_energy` | Daily energy sensor (kWh) | `sensor.solis_energy_today` |

### Scaling options

| Option | Default | Description |
|---|---|---|
| `pv_power_scale` | `1.0` | Multiplier: sensor_value × scale = Watts for register |
| `grid_power_scale` | `1.0` | Multiplier: sensor_value × scale = Watts for register |
| `total_energy_scale` | `10.0` | Multiplier: sensor_value × scale = register units (default: kWh × 10 = 0.1 kWh) |
| `daily_energy_scale` | `10.0` | Multiplier: sensor_value × scale = register units (default: kWh × 10 = 0.1 kWh) |

### Grid power sign convention

| Option | Values | Description |
|---|---|---|
| `grid_power_sign_convention` | `negate` / `direct` | How to convert your sensor's sign to Solis convention |

**Solis register 33263 convention:** positive = exporting to grid, negative = importing from grid.

- **`negate`** — Use if your sensor reports positive=import, negative=export (most common, e.g. Tibber Pulse, most energy meters)
- **`direct`** — Use if your sensor already matches Solis convention (positive=export)

### Other options

| Option | Default | Description |
|---|---|---|
| `enable_http` | `false` | Enable HTTP server on port 80 (discovery experiments) |
| `log_raw_hex` | `false` | Log raw Modbus PDU hex (debug mode) |
| `mirror_writes` | `false` | Mirror Modbus writes internally (no forwarding) |
| `fake_vendor` | `Ginlong` | Vendor string in Device ID response |
| `fake_inverter_model` | `Solis S6-EH1P` | Model in Device ID response |
| `fake_logger_model` | `S2-WL-ST` | Logger model in Device ID |
| `fake_serial` | `S2WLSTFAKE001` | Serial number in Device ID |

## Register Mapping

### Data registers (polled by Tibber every 10 seconds)

| Register | Type | Source | Scaling | Description |
|---|---|---|---|---|
| **33057–33058** | U32 | `ha_sensor_pv_power` | × `pv_power_scale` | PV active power (W) |
| **33263–33264** | S32 | `ha_sensor_grid_power` | × `grid_power_scale`, sign per convention | Grid power (W) |
| **34391–34393** | U32+U16 | `ha_sensor_total_energy` | × `total_energy_scale` | Total lifetime energy |
| **34621–34622** | U32 | `ha_sensor_daily_energy` | × `daily_energy_scale` | Daily energy |
| **33121** | U16 | — | Fixed 0 | Battery direction (idle) |
| **33135–33151** | 17×U16 | — | Fixed 0 | Battery block (no battery) |
| **33245** | U16 | — | Fixed 0 | Battery SoC (0%) |
| **34351** | U16 | — | Fixed 0 | Battery power (0W) |

### Identity registers (read during Tibber discovery)

| Register | Value | Description |
|---|---|---|
| **35000** | `2030` (0x07EE) | Inverter type: 1-phase LV hybrid |
| **33004–33018** | ASCII `"S6-EH1P-6K  S2WLSTFAKE001"` | Model/Serial |

These are loaded from `/share/fake_solis_probe/registers.json`.

### Word order (all U32/S32 registers)

**HI word first** (register N), **LO word second** (register N+1).
Standard Modbus big-endian. No byte/word swap.

### S32 signed encoding

Two's complement. Example: -800 → `0xFFFFFCE0` → hi=`0xFFFF`, lo=`0xFCE0`.

## Startup Validation

The addon validates at startup:

1. All four sensor options are non-empty
2. All entity IDs start with `sensor.`
3. Each entity exists in Home Assistant (API check)
4. `grid_power_sign_convention` is `negate` or `direct`
5. All scaling factors are positive numbers

If validation fails, the addon **will not start the Modbus server** and exits with code 1.
The error is logged clearly in both the addon log and `events.jsonl`.

With **Watchdog** enabled, HA will keep retrying — fix the config and the addon starts automatically.

## Error Handling During Operation

If a sensor returns `unavailable`, `unknown`, or an API error during polling:

- **Last known value is kept** and continues to be served to Tibber
- If no value was ever read: register returns **0**
- Errors are logged with **backoff** (first occurrence + every ~60 seconds), not every 5-second cycle

## Logs

### View logs in HA
**Settings → Add-ons → Fake Solis Probe → Log**

### Event log via Samba
```
\\<HA-IP>\share\fake_solis_probe\events.jsonl
```

### Enable debug logging
1. Go to **Configuration** tab
2. Set `log_raw_hex` to `true`
3. Click **Save** then **Restart**

Now every Modbus request/response is logged as raw hex in `events.jsonl`.

## Dependencies

| Component | Purpose |
|---|---|
| **Any Modbus/API integration** | Provides PV power and energy sensors to HA |
| **Grid power sensor** | Signed net grid power (e.g. from Tibber Pulse, energy meter) |
| **Tibber Bridge** | Polls our Modbus server every 10 seconds |

## Files

| File | Description |
|---|---|
| `/share/fake_solis_probe/events.jsonl` | Structured event log (JSONL) |
| `/share/fake_solis_probe/registers.json` | Preloaded register values (identity) |
