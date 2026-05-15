# Troubleshooting

## Addon Doesn't Appear in Local Add-ons

**Symptom:** After copying files to `/addons/fake_solis_probe/`, the addon doesn't show up.

**Checklist:**
1. File and folder name must be exactly `fake_solis_probe` (underscore, not hyphen)
2. `config.yaml` must exist in that folder
3. Line endings must be **LF** (Unix), not CRLF (Windows). If you edited files on Windows,
   use a tool that enforces LF (e.g. VS Code with `files.eol: "\n"`)
4. Go to **Settings → Add-ons → ⋮ menu → Check for updates** (or Reload)
5. If still missing, restart HA Core

**Verify config.yaml syntax:**
```bash
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))" && echo OK
```

---

## Addon Won't Start — Port 502 Conflict

**Symptom:** Addon crashes immediately with `[Errno 98] Address already in use`

**Check for existing Modbus listeners:**
From HA Terminal addon or SSH:
```bash
ss -ltnp | grep ':502'
```

If something else is using port 502 (another Modbus addon, a real Solis integration
pointed at the wrong host, etc.), you must disable it first.

---

## Addon Won't Start — Configuration Validation Failed

**Symptom:** Log shows `[FATAL] Option 'ha_sensor_pv_power' is empty` or
`entity not found in HA: Entity not found (404)`

**Fix:**
1. Go to **Configuration** tab in the addon
2. Fill in all four `ha_sensor_*` fields with valid HA entity IDs
3. You can find entity IDs in **Developer Tools → States**
4. Click **Save** then **Restart**

The addon will re-validate on each start and log which entity failed if still wrong.

---

## Tibber Can't Find Inverter

**Symptom:** Tibber app scans and times out — "We can't find any inverter on this network"

**Checklist:**
1. The addon must be **running** (green dot in HA)
2. Tibber Bridge and HA must be on the **same LAN subnet** (same router/VLAN)
3. No firewall blocking port 502 between Tibber Bridge IP and HA IP
4. No other device on the LAN is already listening on port 502
5. Try: `telnet <HA-IP> 502` from another device — should connect

**If you have multiple HA addons that use Modbus:**
Check for conflicts. Only one service can bind to port 502.

---

## Values Look Wrong in Tibber App

### PV power is 4× too high
Your sensor is probably reporting in W but `pv_power_scale` is set to a large value,
or vice versa. Check `sensor_poll_values` events in `events.jsonl`:
```json
{"kind":"sensor_poll_values","values":{"sensor.your_pv_power": 4030.0}}
```
The raw value `4030.0` with scale `1.0` → register value `4030` W = 4.03 kW. ✅

### Grid power shows wrong sign
You see import when you should see export (or vice versa). Toggle
`grid_power_sign_convention` between `negate` and `direct`.

To verify: on a sunny day with low consumption you should be **exporting**.
In that state, register 33263–33264 should be **positive** (Solis convention: +export).

### Energy totals wrong scale
If total energy shows e.g. 3002500 instead of 30025 kWh: `total_energy_scale` is 1000
instead of 10. Default `10.0` assumes sensor is in kWh and register wants 0.1 kWh units.

---

## How to Enable Debug Logging

1. **Configuration** tab → set `log_raw_hex: true` → **Save** → **Restart**
2. Every Modbus request and response is now logged as hex in the addon log and in
   `events.jsonl` under `kind: modbus_request_raw` / `modbus_response_raw`

**Disable after debugging:** set back to `false` and restart. Log files can grow large.

---

## How to Analyze events.jsonl

The event log is at `/share/fake_solis_probe/events.jsonl` (accessible via Samba at
`\\<HA-IP>\share\fake_solis_probe\events.jsonl`).

**Normal startup sequence:**
```json
{"kind":"probe_start","version":"0.4.0"}
{"kind":"config_entity_ok","entity_id":"sensor.xxx","detail":"state=4030, unit=W"}
{"kind":"config_validation_passed"}
{"kind":"sensor_poll_started"}
{"kind":"modbus_server_started","port":502}
```

**Normal polling pattern (every 10s from Tibber):**
```json
{"kind":"modbus_read_registers","start":33057,"end":33058,"qty":2}
{"kind":"modbus_read_registers","start":33245,"end":33245,"qty":1}
... (8 blocks total)
```

**Sensor unavailable with backoff:**
```json
{"kind":"sensor_unavailable","entity_id":"sensor.xxx","consecutive_errors":1,"using_last_value":4030.0}
```
This is logged on first error and then every ~60 seconds (not every 5-second poll).

---

## How to Verify S32 Negative Grid Values

At night or when consuming more than producing, grid power should be negative
(importing). To verify:

```python
# Check what -800W looks like as S32 HI/LO
val = -800
twos = (val + 0x100000000) & 0xFFFFFFFF
hi = (twos >> 16) & 0xFFFF  # 0xFFFF = 65535
lo = twos & 0xFFFF           # 0xFCE0 = 64736
```

In `events.jsonl` with `log_raw_hex: true`, you can verify the raw register values
in the `modbus_response_raw` PDU bytes.
