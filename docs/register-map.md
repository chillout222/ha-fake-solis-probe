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

## Periodic Input Registers (FC4) — Read at Connection + Hourly

These registers are read at initial connection AND approximately once per hour
during ongoing operation (observed: every 60 minutes exactly):

| Register | Qty | Observed Content | Purpose |
|---|---|---|---|
| **33004–33018** | 15 | ASCII model/serial string | Inverter identification / display in Tibber app |
| **33067** | 1 | 0 | Unknown (possibly firmware status) |
| **34502–34503** | 2 | 0 | Unknown (possibly total export energy) |
| **35000** | 1 | **2030** (configurable) | Inverter type code — critical for model validation |

**Observation from 26h production log:**
```
reg=33004  reads=27   (2-3 at connect + once per hour)
reg=35000  reads=27   (identical pattern to 33004)
reg=33057  reads=8921 (every 10 seconds — the live data registers)
```

Registers 33004 and 35000 are read with identical frequency, suggesting Tibber
re-validates the inverter identity every hour. This is relevant for `fake_inverter_type_code`:
if you change it after pairing, Tibber will see the new value within ~60 minutes.

### Inverter Type Code (Register 35000)

This is the value that determines which Solis inverter model Tibber recognizes.
It is configurable via the `fake_inverter_type_code` option (v0.6.0+).

| Code | Category | Phase | Voltage | Models | Tibber status |
|---|---|---|---|---|---|
| **1010** | String inverter | 1-phase | — | S5-GC, S6-GR1P | Not expected to work |
| **1020** | String inverter | 3-phase | — | S5-GR3P, S6-GR3P | Not expected to work |
| **2030** | LV Hybrid | 1-phase | LV | S6-EH1P | ✅ **Verified with Tibber** |
| **2031** | LV AC-coupled | 1-phase | LV | S6-AC1P | Untested |
| **2040** | HV Hybrid | 1-phase | HV | S5-EH1P, S6-EH1P-HV | Untested |
| **2050** | LV Hybrid | 3-phase | LV | S6-EH3P | ⚠️ Smoke-tested (experimental) |
| **2060** | HV Hybrid | 3-phase | HV | S5-EH3P HV | Untested |

> **Default and verified: type code 2030 (S6-EH1P).** Use this unless you have a
> specific reason to experiment with another code.
> Type code 2050 (S6-EH3P) has been smoke-tested — Tibber Bridge connected and
> Tibber app opened normally in one installation — but is not long-term verified.
> 2040 and 2060 are untested. If you test a code successfully, open an issue.

### Model String vs. Type Code

Registers 33004–33018 contain a 30-byte ASCII string (model + serial). This is
**independent** of register 35000 (type code). Based on empirical observation:

- **Register 35000** (type code) is likely used by Tibber for **model validation** — this
  is the value that determines whether Tibber accepts the inverter during pairing.
- **Registers 33004–33018** (ASCII string) are likely **cosmetic display** — shown in
  Tibber's inverter info view but not used for protocol compatibility decisions.

**Default configuration (verified):**
```
fake_inverter_type_code: 2030   → register 35000 = 0x07EE
fake_inverter_model: Solis S6-EH1P  → registers 33004-33018 = ASCII "Solis S6-EH1P\x00...S2WLSTFAKE001"
```

**Experimental 3-phase configuration (smoke-tested, not long-term verified):**
```
fake_inverter_type_code: 2050   → register 35000 = 0x0802
fake_inverter_model: Solis S6-EH3P  → registers 33004-33018 = ASCII "Solis S6-EH3P\x00...S2WLSTFAKE001"
```
> ⚠️ Tibber Bridge connected and Tibber app opened normally in one test with 2050.
> Not long-term verified. Monitor your Tibber integration after switching.

A mismatch (e.g., type_code=2050 but model_string="Solis S6-EH1P") will probably
show wrong info in Tibber's app view but not cause functional problems. There is no
auto-sync between these two values — update `fake_inverter_model` manually if you
change `fake_inverter_type_code`.

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

## Function Codes FC17 and FC43 — Implemented but Never Observed

The addon implements two additional Modbus function codes:

| FC | Name | Implementation | Tibber observations |
|---|---|---|---|
| **FC17** | Report Server ID | Returns vendor/model ASCII string | **0 reads in 26h of operation** |
| **FC43** | Read Device Identification | Returns structured vendor/model/serial objects | **0 reads in 26h of operation** |

Neither FC17 nor FC43 was ever called by Tibber Bridge during 26+ hours of
continuous operation, including initial discovery and pairing.

**Why are they implemented?**

They were included as *defensive coding* during development, based on the Modbus
specification and the assumption that Tibber might use them for device identification.
This turned out to be incorrect — Tibber uses FC4 register reads for all identification
(registers 33004–33018 and 35000).

**For contributors:** FC17 and FC43 can safely be considered non-critical. They are
retained because:
1. They add robustness if future Tibber Bridge firmware versions adopt them
2. Removal would make the addon non-standard Modbus
3. They add negligible code complexity

If you are debugging a Tibber connection issue, focus on register 35000 (type code)
and the FC4 data registers — not on FC17 or FC43.
