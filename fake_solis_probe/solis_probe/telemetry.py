"""Convert cached Home Assistant values into the fake inverter register map."""

from __future__ import annotations

from typing import Optional

from . import config, event_log, registers, sensor_cache


# Fallback logging backoff: (entity_id, behavior) -> consecutive_fallback_count
FALLBACK_LOG_COUNT: dict[str, int] = {}


def reset_fallback_log_counts() -> None:
    """Clear fallback backoff state for an isolated test or fresh runtime."""
    FALLBACK_LOG_COUNT.clear()


def apply_behavior(
    entity_id: str,
    raw: Optional[float],
    behavior: str,
    scale: float,
    error_count: int,
    last_known_val: Optional[float] = None,
) -> Optional[float]:
    """Apply unavailable behavior when ``raw`` is None.

    Args:
        raw: Current sensor reading from ``SENSOR_CACHE``. It must be None
            when a sensor is unavailable; the polling loop is responsible for
            setting ``SENSOR_CACHE[entity]`` to None on failed polls (the
            v0.5.1 fix).
        last_known_val: Last successful reading from ``LAST_KNOWN_CACHE``.
            It is used only for logging, not to compute the return value.

    Returns:
        float: Scaled value to write into the Modbus register.
        None: With behavior ``last_known``, do not overwrite the register.
            It retains the value written on the last successful poll. This is
            intentional for cumulative values such as total energy that must
            never decrease or be zeroed.
    """
    if raw is not None:
        return raw * scale

    # Sensor is unavailable — apply configured fallback.
    if behavior == "zero":
        written_value: Optional[float] = 0.0
    else:  # last_known — leave the register unchanged
        written_value = None

    # Log with backoff (same interval as sensor_unavailable: every ~60 s).
    key = f"{entity_id}:{behavior}"
    count = FALLBACK_LOG_COUNT.get(key, 0) + 1
    FALLBACK_LOG_COUNT[key] = count
    if count == 1 or count % config.ERROR_LOG_INTERVAL == 0:
        event_log.log_event(
            "register_fallback",
            entity_id=entity_id,
            behavior=behavior,
            written_value=written_value,
            last_known_value=last_known_val,
            consecutive_errors=error_count,
        )
    return written_value


def reset_fallback_count(entity_id: str, behavior: str) -> None:
    """Reset one unavailable-value logging backoff after sensor recovery."""
    FALLBACK_LOG_COUNT.pop(f"{entity_id}:{behavior}", None)


def update_live_registers() -> None:
    """Push cached Home Assistant sensor values into the register map."""
    pv_entity = str(config.OPTIONS.get("ha_sensor_pv_power", ""))
    grid_entity = str(config.OPTIONS.get("ha_sensor_grid_power", ""))
    total_entity = str(config.OPTIONS.get("ha_sensor_total_energy", ""))
    daily_entity = str(config.OPTIONS.get("ha_sensor_daily_energy", ""))

    sign_convention = str(config.OPTIONS.get("grid_power_sign_convention", "negate"))
    pv_scale = float(config.OPTIONS.get("pv_power_scale", 1.0))
    grid_scale = float(config.OPTIONS.get("grid_power_scale", 1.0))
    total_scale = float(config.OPTIONS.get("total_energy_scale", 10.0))
    daily_scale = float(config.OPTIONS.get("daily_energy_scale", 10.0))

    pv_behavior = str(config.OPTIONS.get("pv_power_unavailable_behavior", "zero"))
    grid_behavior = str(config.OPTIONS.get("grid_power_unavailable_behavior", "zero"))
    total_behavior = str(
        config.OPTIONS.get("total_energy_unavailable_behavior", "last_known")
    )
    daily_behavior = str(
        config.OPTIONS.get("daily_energy_unavailable_behavior", "zero")
    )

    with sensor_cache.CACHE_LOCK:
        # Current readings — None when a sensor is unavailable.
        pv_raw = sensor_cache.SENSOR_CACHE.get(pv_entity)
        grid_raw = sensor_cache.SENSOR_CACHE.get(grid_entity)
        total_raw = sensor_cache.SENSOR_CACHE.get(total_entity)
        daily_raw = sensor_cache.SENSOR_CACHE.get(daily_entity)

        # Last known values — retained across unavailable periods.
        pv_last_known = sensor_cache.LAST_KNOWN_CACHE.get(pv_entity)
        grid_last_known = sensor_cache.LAST_KNOWN_CACHE.get(grid_entity)
        total_last_known = sensor_cache.LAST_KNOWN_CACHE.get(total_entity)
        daily_last_known = sensor_cache.LAST_KNOWN_CACHE.get(daily_entity)

        # Resolve error counts for backoff logging.
        pv_errors = sensor_cache.SENSOR_ERROR_COUNT.get(pv_entity, 0)
        grid_errors = sensor_cache.SENSOR_ERROR_COUNT.get(grid_entity, 0)
        total_errors = sensor_cache.SENSOR_ERROR_COUNT.get(total_entity, 0)
        daily_errors = sensor_cache.SENSOR_ERROR_COUNT.get(daily_entity, 0)

    # Reset fallback counters for sensors that have recovered.
    if pv_raw is not None:
        reset_fallback_count(pv_entity, pv_behavior)
    if grid_raw is not None:
        reset_fallback_count(grid_entity, grid_behavior)
    if total_raw is not None:
        reset_fallback_count(total_entity, total_behavior)
    if daily_raw is not None:
        reset_fallback_count(daily_entity, daily_behavior)

    pv_value = apply_behavior(
        pv_entity,
        pv_raw,
        pv_behavior,
        pv_scale,
        pv_errors,
        pv_last_known,
    )
    # Grid: apply scale and behavior first, then sign convention on the
    # resolved value.
    grid_value = apply_behavior(
        grid_entity,
        grid_raw,
        grid_behavior,
        grid_scale,
        grid_errors,
        grid_last_known,
    )
    total_value = apply_behavior(
        total_entity,
        total_raw,
        total_behavior,
        total_scale,
        total_errors,
        total_last_known,
    )
    daily_value = apply_behavior(
        daily_entity,
        daily_raw,
        daily_behavior,
        daily_scale,
        daily_errors,
        daily_last_known,
    )

    with registers.REG_LOCK:
        # 33057-33058: PV Active Power (U32, W)
        if pv_value is not None:
            high_word, low_word = registers.to_u32_pair(int(pv_value))
            registers.REGS[33057] = high_word
            registers.REGS[33058] = low_word

        # 33263-33264: Grid Import/Export Power (S32, W)
        if grid_value is not None:
            grid_watts = int(grid_value)
            if sign_convention == "negate":
                grid_watts = -grid_watts
            high_word, low_word = registers.to_s32_pair(grid_watts)
            registers.REGS[33263] = high_word
            registers.REGS[33264] = low_word

        # 34391-34393: Total Energy (U32 in scaled units + trailing U16)
        if total_value is not None:
            high_word, low_word = registers.to_u32_pair(int(total_value))
            registers.REGS[34391] = high_word
            registers.REGS[34392] = low_word
            registers.REGS[34393] = 0

        # 34621-34622: Daily Energy (U32 in scaled units)
        if daily_value is not None:
            high_word, low_word = registers.to_u32_pair(int(daily_value))
            registers.REGS[34621] = high_word
            registers.REGS[34622] = low_word

        # Battery registers — always zero (no battery).
        registers.REGS[33121] = 0
        registers.REGS[33245] = 0
        registers.REGS[34351] = 0
        for address in range(33135, 33152):
            registers.REGS[address] = 0
