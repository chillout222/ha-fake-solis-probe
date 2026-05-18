# Changelog

## [0.7.0] - 2026-05-18

### Added
- **Log rotation for `events.jsonl`** — prevents unbounded file growth on the
  host volume.
  - `log_max_bytes` (default `5242880` = 5 MB): rotate when the file exceeds
    this size. Set to `0` to disable rotation entirely.
  - `log_backup_count` (default `3`): number of backup files to keep
    (`.1`, `.2`, `.3`). Set to `0` to truncate in-place with no backups.
  - Maximum on-disk usage: `log_max_bytes × (log_backup_count + 1)` ≈ 20 MB
    with defaults.
  - Rotation runs inside the existing `LOG_LOCK` critical section in
    `log_event()`, immediately before the new line is appended — so every new
    event always lands in a fresh `events.jsonl` after rotation.
  - Rotation failures are printed to stdout but never crash the addon or
    drop events.
  - A `[Fake Solis Probe] log rotated: …` message is printed to the HA
    add-on log on each rotation (not written to `events.jsonl` itself, to
    avoid a log-about-logging loop).
- `fake_solis_probe/tests/test_log_rotation.py` — standalone regression test
  suite (8 tests) using a real temporary directory and real file I/O, covering
  threshold detection, cascade rename, backup_count=0 truncation,
  max_bytes=0 disable, and missing-file safety.

## [0.5.1] - 2026-05-17

### Fixed
- **Phantom production bug not fully resolved by v0.5.0** — root cause identified
  and fixed: `SENSOR_CACHE` was never set to `None` when a sensor became unavailable.
  The stale last-known value remained in the cache (e.g. `energy_today = 30.6`),
  causing `_apply_behavior()` to receive a non-None `raw` value and skip the
  configured fallback entirely. The `zero` behavior for `daily_energy` therefore
  never wrote 0 to the register. Result: Tibber continued displaying ~306 W phantom
  production (30.6 kWh × scale 10 = 306 units ≈ 306 W).

### Changed
- **`SENSOR_CACHE`** now explicitly set to `None` on every failed poll, correctly
  signalling "unavailable" to `_apply_behavior()`.
- **`LAST_KNOWN_CACHE`** added as a separate dict to retain the last successful
  numeric reading across unavailable periods. Updated atomically with `SENSOR_CACHE`
  under `CACHE_LOCK` on every successful poll.
- **`_apply_behavior()`** gains a `last_known_val` parameter (from `LAST_KNOWN_CACHE`)
  which is included in `register_fallback` log events for better diagnostics.
- **`sensor_unavailable`** log event field renamed from `using_last_value` to
  `last_known_value` for consistency with `register_fallback`.

### Added
- `fake_solis_probe/tests/test_behavior.py` — standalone regression test suite
  verifying the fixed cache behaviour, correct register output for `zero`/`last_known`
  behaviors, and the v0.5.0 stale-value bug path.

### Notes
- Second night verification showed ~306 W phantom production (30.6 kWh × 10),
  confirming the v0.5.0 fix was incomplete. Time-weighted Tibber hourly values
  23:00–03:00 = 306 W exactly matched `energy_today` × scale.
- `register_fallback` events were 0 in the v0.5.0 night log, which was the
  diagnostic key: `_apply_behavior` was never called with `raw=None`.

## [0.5.0] - 2026-05-16

### Fixed
- Daily energy register no longer freezes at previous day's value when
  Solis inverter goes offline at night. This previously caused Tibber
  to display incorrect "production" values during nighttime hours
  (Tibber Bridge interprets daily energy register as a power indicator
  for hourly aggregation).

### Added
- Per-sensor `*_unavailable_behavior` options (`zero` | `last_known`)
- Explicit `register_fallback` log event with consecutive error counts
  and written value, using same backoff as `sensor_unavailable`
- Safe defaults: PV power → zero, grid power → zero,
  total energy → last_known (cumulative), daily energy → zero

### Notes
- Fix for a problem observed during the first 24-hour production test,
  where Tibber displayed ~740 W of phantom production during the night,
  corresponding to the previous day's energy_today value
  (74.0 kWh × scale 10 = 740). Time-weighted averaging of hourly Tibber
  values matched this hypothesis exactly: 04:00 = 539 W (mix of 74 kWh
  and 0 kWh after 04:43 recovery), 05:00 = 128 W (real PV ramp-up).

## [0.4.0] — 2026-05-15

### Changed
- **Sensor entity IDs are now configurable** via addon Configuration UI
  - `ha_sensor_pv_power`, `ha_sensor_grid_power`, `ha_sensor_total_energy`, `ha_sensor_daily_energy`
  - No more hardcoded entity IDs — required for multi-user support
- **Scaling factors are configurable**: `pv_power_scale`, `grid_power_scale`, `total_energy_scale`, `daily_energy_scale`
- **Grid power sign convention is configurable**: `grid_power_sign_convention` = `negate` or `direct`

### Added
- **Startup validation**: addon refuses to start if sensor entity IDs are empty, invalid, or don't exist in HA
- **Error backoff**: unavailable sensors logged with backoff (first error + every 60s), not every 5s cycle
- **Graceful degradation**: if a sensor goes unavailable during operation, last known value is used
- `CHANGELOG.md`

### Removed
- Hardcoded `SENSOR_ACTIVE_POWER`, `SENSOR_GRID_POWER`, etc. constants
- `ha_sensor_test_entity` option (replaced by proper sensor config)

## [0.3.0] — 2026-05-15

### Changed
- `boot: auto` (was manual)
- Default `log_raw_hex: false` (was true)
- Default `mirror_writes: false` (was true)
- Grid sensor switched from dead Solis meter (no physical CT clamp) to a signed net-grid power sensor from Tibber Pulse

### Added
- `README.md`

## [0.2.0] — 2026-05-15

### Added
- Phase 2: Live HA sensor data → Modbus registers
- Background polling thread (5s interval)
- HA Supervisor API integration via `SUPERVISOR_TOKEN`

### Register mapping
- 33057–33058: PV Active Power (U32, W)
- 33263–33264: Grid Power (S32, W)
- 34391–34393: Total Energy (U32, 0.1 kWh)
- 34621–34622: Daily Energy (U32, 0.1 kWh)
- Battery registers: all zero

## [0.1.0] — 2026-05-15

### Added
- Initial release: Modbus TCP server on port 502
- Tibber Bridge discovery support (register 35000, 33004–33018)
- Event logging to `/share/fake_solis_probe/events.jsonl`
- Register hot-reload from `registers.json`
- Device ID (FC43) emulation
