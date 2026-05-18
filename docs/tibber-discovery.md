# Tibber Discovery Sequence

This document describes the observed sequence of events when Tibber Bridge
discovers and connects to the emulated inverter.

> **Disclaimer:** This is based on empirical observation via Modbus packet logging.
> Tibber has not published documentation of this protocol. It may change without notice.

## Discovery Flow

### Phase 1 — LAN Scan (Tibber Bridge)

Tibber Bridge scans the local LAN subnet for open port 502 (standard Modbus TCP).
This scan is triggered from the Tibber mobile app when you start the inverter setup flow.

**Requirement:** The addon must be running and port 502 must be reachable from Tibber
Bridge on the same LAN segment.

### Phase 2 — Model Identification

Tibber reads register 35000 (FC4, 1 register):

```
FC4, start=35000, qty=1 → returns configured type code

Default:      2030 (0x07EE) — S6-EH1P   ✅ verified default
3-Phase:      2050 (0x0802) — S6-EH3P   ✅ verified in one installation
```

The returned value identifies the inverter model to Tibber Bridge.
If Tibber does not recognize the type code, it will not proceed.

> **Default `fake_inverter_type_code: 2030` is the recommended default for maximum compatibility.**
> Type code `2050` (S6-EH3P) has been **verified in one 3-phase installation** (overnight behavior confirmed with v0.6.0 on 2026-05-17/18).
> It is recommended for 3-phase setups, though not universally verified across all environments.

Tibber then reads registers 33004–33018 (FC4, 15 registers) to get the model/serial
ASCII string.

### Phase 3 — App Confirmation

The Tibber app shows the identified model, e.g.:
- **Default (2030):** *"Found your inverter — Solis S6-EH1P"*
- **3-Phase (2050):** App behavior remained normal; no model-specific display difference was observed in the tested installation (it displayed the generic Solis inverter view), and overnight data flow is verified in one 3-phase installation.

The app then asks: **"Confirm battery capacity"**

Enter **0** to indicate no battery. The app accepts this and shows:
*"Your Solis inverter is connected."*

### Phase 4 — Initial Configuration Reads (One-Time)

After confirmation, Tibber reads several holding registers (FC3) and additional input
registers (FC4) once. These appear to be for configuration/metadata purposes.
All return 0 without adverse effect. See [register-map.md](register-map.md) for the
full list.

### Phase 5 — Continuous Polling

Tibber Bridge enters continuous polling mode:

- **Interval:** Every 10 seconds
- **Connection:** Persistent TCP connection (no reconnect between polls)
- **Blocks per cycle:** 8 register reads (FC4)
- **Order per cycle:**
  1. 33057–33058 (PV power)
  2. 33245 (Battery SoC)
  3. 34391–34393 (Total energy)
  4. 33121 (Battery direction)
  5. 33135–33151 (Battery block)
  6. 33263–33264 (Grid power)
  7. 34351 (Battery power)
  8. 34621–34622 (Daily energy)

## Verified Observations

| Observation | Status |
|---|---|
| Tibber accepts type code 2030 (S6-EH1P) | ✅ Verified default |
| Tibber Bridge connects with type code 2050 (S6-EH3P) | ✅ Verified in one installation (overnight operation confirmed) |
| Tibber polls every ~10 seconds | ✅ Verified |
| Tibber holds persistent TCP connection | ✅ Verified (no reconnects observed over hours) |
| Tibber makes no write requests (FC6/FC16) | ✅ Verified (read-only confirmed) |
| Battery capacity 0 accepted without error | ✅ Verified |
| Scaling factors validated against V×I calculations | ✅ Verified |
| S32 two's complement round-trip verified | ✅ Verified |

## What Happens If the Addon Restarts

Tibber Bridge will detect the TCP connection drop and attempt to reconnect.
In testing, it reconnects within a few seconds and resumes polling.
No re-pairing in the Tibber app is required.
