# Changelog

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
