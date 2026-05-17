# ha-fake-solis-probe

**Makes Tibber Bridge work with non-hybrid Solis inverters by emulating a Solis S6-EH1P over Modbus TCP.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/addon%20version-0.6.0-blue)](fake_solis_probe/CHANGELOG.md)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-HAOS%20Addon-41BDF5?logo=home-assistant)](https://www.home-assistant.io/)
![Status: Experimental](https://img.shields.io/badge/status-experimental-orange)

> ⚠️ **Disclaimer:** This is an independent community project. It is not affiliated with,
> endorsed by, or supported by Tibber AS or Ginlong Solis. Use at your own risk.
> Future firmware updates by Tibber or Solis may break functionality without notice.

---

## Why does this exist?

Tibber's Solis integration only supports **hybrid** inverter models (S5/S6 EH1P, EH3P, RHI, EA1P).
If you have a **string inverter** (Solis 5P, S5 GR3P, S6 GR1P, etc.), Tibber will tell you
your model is not supported.

This Home Assistant addon solves that by running a local Modbus TCP server that **emulates a
Solis S6-EH1P hybrid inverter**, feeding real-time PV data from your existing HA sensors to
Tibber Bridge — without touching your real inverter or datalogger.

---

## How It Works

```
Your inverter → HA integration → HA sensors
                                      ↓
                            Fake Solis Probe addon
                            (Modbus TCP :502, emulates S6-EH1P)
                                      ↓
                             Tibber Bridge (LAN)
                                      ↓
                              Tibber Cloud → Tibber app
```

The addon reads four configurable HA sensor entities every 5 seconds and serves the data
to Tibber Bridge, which polls every 10 seconds. Your real inverter hardware is never contacted.

See [docs/architecture.md](docs/architecture.md) for full technical details.

---

## What's Been Verified

These observations were made empirically during development:

- ✅ Tibber Bridge accepts inverter type code `2030` (S6-EH1P) as a valid model
- ✅ Tibber Bridge polls 8 register blocks every 10 seconds (FC4, Input Registers)
- ✅ Persistent TCP connection — no reconnects observed over hours of operation
- ✅ Tibber makes **no write requests** — purely read-only integration confirmed
- ✅ Scaling factors verified against physical V×I DC calculations and cloud portal data
- ✅ S32 two's complement encoding verified by round-trip test
- ✅ Battery capacity = 0 accepted by Tibber app without error
- ✅ Startup validation prevents misconfiguration from serving bad data silently

---

## Requirements

- **Home Assistant OS** (tested on HA Green, HAOS 14.x)
- A working **HA integration** for your inverter (Modbus, SolarEdge, Fronius, Huawei, etc.)
  that provides sensors for PV power and energy — **already set up and working**
- A signed **net grid power sensor** in HA (e.g. from Tibber Pulse, a smart meter, or
  your utility's integration) — positive when importing, negative when exporting (or vice versa)
- **Tibber Bridge** on the same LAN
- Active **Tibber subscription**

> The addon works with **any** inverter brand — you just need the right HA sensors.
> See [docs/adapting-for-other-inverters.md](docs/adapting-for-other-inverters.md).

---

## Installation

### Option A — Manual (Samba)

1. Enable the **Samba** addon in HA if not already active
2. Copy the `fake_solis_probe/` folder to `\\<HA-IP>\addons\fake_solis_probe\`
3. In HA: **Settings → Add-ons → ⋮ → Check for updates**
4. Find **Fake Solis Probe** in Local add-ons and click **Install**
5. Go to **Configuration** and fill in your sensor entity IDs (see below)
6. Go to **Info** and enable **Start on boot** + **Watchdog**
7. Click **Start**

### Option B — As HA Add-on Repository

1. Go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (top right) → **Repositories**
3. Add: `https://github.com/Chillout222/ha-fake-solis-probe`
4. Find **Fake Solis Probe** and install
5. Configure and start as above

---

## Configuration

Go to the **Configuration** tab after installing.

### Required — Sensor entity IDs

| Option | Description | Example |
|---|---|---|
| `ha_sensor_pv_power` | PV active power sensor (**W**) | `sensor.solis_active_power` |
| `ha_sensor_grid_power` | Net grid power sensor (**W, signed**) | `sensor.grid_net_power` |
| `ha_sensor_total_energy` | Total lifetime energy (**kWh**) | `sensor.solis_total_energy` |
| `ha_sensor_daily_energy` | Daily energy production (**kWh**) | `sensor.solis_energy_today` |

**How to find entity IDs:** In HA, go to **Developer Tools → States**, filter by `sensor`,
and look for sensors with matching units and names.

### Scaling options

| Option | Default | When to change |
|---|---|---|
| `pv_power_scale` | `1.0` | Set to `1000.0` if your power sensor is in kW |
| `grid_power_scale` | `1.0` | Set to `1000.0` if your grid sensor is in kW |
| `total_energy_scale` | `10.0` | Leave as-is if sensor is in kWh (standard) |
| `daily_energy_scale` | `10.0` | Leave as-is if sensor is in kWh |

### Grid power sign convention

| Option | Description |
|---|---|
| `grid_power_sign_convention: negate` | Your sensor: positive=import, negative=export **(most common)** |
| `grid_power_sign_convention: direct` | Your sensor already matches Solis: positive=export |

To verify: on a sunny day with low consumption, you should be exporting. Check your sensor's
value at that moment — if it's negative, use `negate`. If positive, use `direct`.

### Other options

| Option | Default | Description |
|---|---|---|
| `enable_http` | `false` | Enable HTTP server on port 80 (for discovery experiments) |
| `log_raw_hex` | `false` | Log raw Modbus PDU hex (debug mode — can generate large logs) |
| `mirror_writes` | `false` | Mirror Modbus writes into register cache (writes are never forwarded) |
| `fake_vendor` | `Ginlong` | Vendor string returned in Modbus Device ID |
| `fake_inverter_model` | `Solis S6-EH1P` | Model string returned in Modbus Device ID |
| `fake_serial` | `S2WLSTFAKE001` | Serial number returned in Modbus Device ID |
| `fake_inverter_type_code` | `2030` | Inverter type code in register 35000 — see table below |

### Inverter type code

> **Note:** The emulated inverter type defaults to S6-EH1P (1-phase hybrid, type code 2030).
> Only `2030` is fully verified to work with Tibber Bridge long-term.
> Type code `2050` has been smoke-tested (Modbus + Tibber app) in one installation
> but is not long-term verified. Other codes are untested.
> See [docs/adapting-for-other-inverters.md](docs/adapting-for-other-inverters.md).

| Code | Model | Phase | Tibber status |
|---|---|---|---|
| `2030` | S6-EH1P | 1-phase LV | ✅ Verified |
| `2040` | S5-EH1P HV | 1-phase HV | Untested |
| `2050` | S6-EH3P | 3-phase LV | ⚠️ Smoke-tested (experimental) |
| `2060` | S5-EH3P HV | 3-phase HV | Untested |

---

## Pairing with Tibber

After the addon is running:

1. Open the **Tibber app** → **Settings** → your home → **Solar**
2. Select **Solis** → **S6-EH1P** (or start the inverter setup flow)
3. The app will scan your LAN for port 502 — it should find the addon
4. When asked for battery capacity, enter **0** (no battery)
5. Done — Tibber app will show "Your Solis inverter is connected"

---

## Technical Details

- [Architecture](docs/architecture.md) — full data chain and design decisions
- [Register Map](docs/register-map.md) — empirical Tibber polling pattern and register definitions
- [Tibber Discovery](docs/tibber-discovery.md) — step-by-step connection sequence
- [Adapting for Other Inverters](docs/adapting-for-other-inverters.md) — how to configure for non-Solis setups
- [Troubleshooting](docs/troubleshooting.md) — common problems and fixes

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and PRs welcome.
Please **remove all IP addresses, entity IDs, and personal information** from logs before posting.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

- The [Home Assistant](https://www.home-assistant.io/) community for the excellent addon framework
- The [Ginlong Solis Modbus documentation](https://www.ginlong.com/) for register reference
- [Tibber](https://tibber.com/) — for an otherwise excellent energy service
- AI-assisted architecture, implementation, and documentation
