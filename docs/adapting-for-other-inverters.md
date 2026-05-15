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

Register 35000 contains the inverter type code. We use `2030` (S6-EH1P).
If Tibber adds support for other models in the future, you may want a different code.

Known codes (community-reported, not officially documented):

| Code | Model |
|---|---|
| 2030 | S6-EH1P (1-phase hybrid, tested ✅) |
| Others | Unknown — test empirically |

To change it, edit `/share/fake_solis_probe/registers.json`:
```json
{
  "35000": 2030
}
```

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
