# Modbus Register Map

This document lists all registers observed during Tibber Bridge interaction,
based on empirical testing with a Tibber Bridge on firmware version unknown.

> **Note:** This register map is based on reverse-engineering Tibber's polling
> pattern, not on official Tibber documentation. It may change with future
> Tibber Bridge firmware updates.

## Polled Input Registers (FC4) — Every 10 Seconds

These are the 8 register blocks Tibber polls continuously after connecting:

| Register | Qty | Data Type | Scale | Solis Meaning | Addon Mapping |
|---|---|---|---|---|---|
| **33057–33058** | 2 | U32 (HI first) | ×1 = W | Total AC Active Power | `ha_sensor_pv_power` × `pv_power_scale` |
| **33121** | 1 | U16 | — | Battery Current Direction (0=idle) | Fixed 0 (no battery) |
| **33135–33151** | 17 | mixed | — | Battery data block | Fixed 0 (no battery) |
| **33245** | 1 | U16 | — | Battery State of Charge (%) | Fixed 0 |
| **33263–33264** | 2 | S32 (HI first) | ×1 = W | Meter Total Active Power | `ha_sensor_grid_power` × `grid_power_scale` ± sign |
| **34351** | 1 | U16 | — | Battery Power | Fixed 0 |
| **34391–34393** | 3 | U32 + U16 | ×0.1 kWh | Total Generation Energy | `ha_sensor_total_energy` × `total_energy_scale` |
| **34621–34622** | 2 | U32 (HI first) | ×0.1 kWh | Daily Generation Energy | `ha_sensor_daily_energy` × `daily_energy_scale` |

### U32 Word Order

All 32-bit values use **big-endian, HI word first**:
- Register N = bits 31–16 (high word)
- Register N+1 = bits 15–0 (low word)

This matches standard Solis Modbus implementation.

### S32 Encoding (Register 33263–33264)

Signed 32-bit two's complement, big-endian, HI word first.

| Value | Meaning | Hex | HI Word | LO Word |
|---|---|---|---|---|
| +5000 | Exporting 5000W | 0x00001388 | 0x0000 | 0x1388 |
| -800 | Importing 800W | 0xFFFFFCE0 | 0xFFFF | 0xFCE0 |
| 0 | No grid exchange | 0x00000000 | 0x0000 | 0x0000 |

## One-Time Input Registers (FC4) — Read at Initial Connection

| Register | Qty | Observed Content | Purpose |
|---|---|---|---|
| **33004–33018** | 15 | ASCII model/serial string | Inverter identification |
| **33067** | 1 | 0 | Unknown (possibly firmware status) |
| **34502–34503** | 2 | 0 | Unknown (possibly total export energy) |
| **35000** | 1 | **2030** (0x07EE) | Inverter type code — critical for model validation |

### Inverter Type Code 2030

Register 35000 = `2030` tells Tibber Bridge that this is a **Solis S6-EH1P** (1-phase
low-voltage hybrid). This is the value that makes Tibber accept the inverter.

Other model codes exist for other Solis hybrids (S5 EH3P, RHI, etc.) but have not
been tested. If you need to simulate a different model, this is the register to change.

Preload via `/share/fake_solis_probe/registers.json`:
```json
{
  "35000": 2030
}
```

## One-Time Holding Registers (FC3) — Read at Initial Connection

| Register | Qty | Returns | Notes |
|---|---|---|---|
| 43010–43011 | 2 | 0 | Unknown |
| 43052 | 1 | 0 | Unknown |
| 43073–43074 | 2 | 0 | Unknown |
| 43110 | 1 | 0 | Unknown |
| 43140 | 1 | 0 | Unknown |
| 43483–43488 | 6 | 0 | Unknown (possibly grid config) |

All return 0. No adverse effects observed from returning zeros for these registers.

## Battery Registers — Always Zero

The addon permanently returns 0 for all battery registers. This tells Tibber that
there is no battery (SoC = 0%, power = 0W, direction = idle).

When Tibber asks "What is your battery capacity?", enter **0** to indicate no battery.
