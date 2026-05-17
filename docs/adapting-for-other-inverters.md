# Adapting for Other Inverters

This addon was developed and tested with a **Solis 5P** string inverter and
**S2-WL-ST** datalogger. However, the design is intentionally generic.
This guide explains how to adapt it for other setups.

## Step 1 — Find Your HA Sensor Entity IDs

You need four sensors already available in Home Assistant:

| Role | Unit | How to find it |
|---|---|---|
| PV active power | W | Developer Tools → States → search "power" or "watt" |
| Net grid power | W, signed | Same — look for a sensor that goes negative when exporting |
| Total lifetime energy | kWh | Search "total energy" or "lifetime" |
| Daily energy | kWh | Search "today" or "daily" |

**Tip:** In Developer Tools → States, filter by `sensor` and look at
`unit_of_measurement`. If your inverter integration uses kW instead of W,
set `pv_power_scale: 1000.0`.

## Step 2 — Verify Scaling Factors

### Power sensors (Watts)

The PV power register (33057–33058) expects raw Watts.

| Your sensor unit | Scale to use |
|---|---|
| W (watts) | `1.0` |
| kW (kilowatts) | `1000.0` |

### Energy sensors (0.1 kWh)

The energy registers expect values in **0.1 kWh units** (i.e. 10 × kWh).

| Your sensor unit | Scale to use |
|---|---|
| kWh | `10.0` |
| Wh | `0.01` |
| MWh | `10000.0` |

### Cross-check your values

Verify PV power against physical measurements:
```
P = V1 × I1 + V2 × I2 + ...  (sum of DC string power)
AC output ≈ DC × efficiency (typically 0.96–0.98)
```

Compare against your inverter's cloud portal or existing HA integration.

## Step 3 — Grid Power Sign Convention

Determine how your grid sensor reports power flow:

| Sensor behavior | Setting |
|---|---|
| Positive = import from grid, negative = export | `negate` |
| Positive = export to grid, negative = import | `direct` |

To verify: watch the sensor value when you know you are exporting (sunny day,
low consumption). If the value is negative → use `negate`. If positive → use `direct`.

## Step 4 — Choosing a Solis Inverter Type to Emulate

Register 35000 contains the inverter type code that tells Tibber Bridge which
Solis model it is talking to. From v0.6.0 this is configurable via the
`fake_inverter_type_code` option in the **Configuration** tab — no file editing needed.

### Known type codes

| Code | Category | Phase | Battery voltage | Typical models | Tibber status |
|---|---|---|---|---|---|
| **2030** | LV Hybrid | 1-phase | LV | S6-EH1P | ✅ **Verified** |
| **2031** | LV AC-coupled | 1-phase | LV | S6-AC1P | Untested |
| **2040** | HV Hybrid | 1-phase | HV | S5-EH1P, S6-EH1P-HV | Untested |
| **2050** | LV Hybrid | 3-phase | LV | S6-EH3P | ⚠️ Smoke-tested (experimental) |
| **2060** | HV Hybrid | 3-phase | HV | S5-EH3P HV | Untested |

> **Only type code 2030 is fully verified with Tibber Bridge.**
> Type code 2050 has been smoke-tested (Modbus + Tibber app) in one installation
> with no errors observed, but is not considered long-term verified.
> 2040 and 2060 are untested. If you test any code successfully, please open a
> GitHub issue to update this table.

### Recommended settings by installation type

**1-phase hybrid (default):**
```
fake_inverter_type_code: 2030
fake_inverter_model: Solis S6-EH1P
```

**3-phase hybrid (smoke-tested in one installation — experimental):**
```
fake_inverter_type_code: 2050
fake_inverter_model: Solis S6-EH3P
```
> ⚠️ Tibber Bridge connected and Tibber app opened normally in one test.
> Not long-term verified. Monitor your Tibber integration after changing.

### Model string vs. type code

`fake_inverter_model` (register 33004–33018) and `fake_inverter_type_code`
(register 35000) are **independent**. Tibber reads both roughly once per hour.

- **Type code** determines whether Tibber accepts the inverter (validation)
- **Model string** is likely cosmetic display in the Tibber app

There is no auto-sync between them. If you change `fake_inverter_type_code`,
update `fake_inverter_model` manually to match.

### Register 35000 priority

**At startup:** `fake_inverter_type_code` is written to register 35000 **after**
registers.json is loaded. This means the config option wins at startup, even if
registers.json contains a `"35000"` key.

**During runtime (hot-reload):** The addon monitors registers.json for file changes.
If you edit registers.json while the addon is running and add or change a `"35000"` key,
that value will be picked up on the next Modbus poll (within 10 seconds) and will
override the startup value for the remainder of that session.

**Recommendation:** Do not set `"35000"` in registers.json unless you specifically
want hot-reload override behavior. Use `fake_inverter_type_code` in the Configuration
tab instead — it is the intended control surface.

> **Note on config.yaml comments:** The `#`-comments in config.yaml are not shown
> in the HA Configuration tab. The UI only displays option names and their values.
> Refer to this document and the README for option descriptions.


## Step 5 — Using Probe Mode to Debug

If Tibber does not connect or data looks wrong, enable debug logging:

1. Go to **Configuration** tab → set `log_raw_hex: true` → Save → Restart
2. Watch the **Log** tab or `events.jsonl` for raw Modbus traffic
3. Look for `modbus_read_registers` events to see what registers Tibber requests
4. Look for `sensor_poll_values` to see what your sensors are reporting

## Non-Solis Inverters

Any inverter with HA sensors for PV power and energy can work. The addon emulates
a *Solis* to Tibber Bridge — your real inverter brand is irrelevant.

Requirements:
- A HA sensor reporting current PV production in W (or kW, with scaling)
- A HA sensor for net grid power (signed)
- HA sensors for total and daily energy production

These can come from any integration: SolarEdge, Fronius, SMA, Huawei, Goodwe,
Enphase, or any generic energy meter.
