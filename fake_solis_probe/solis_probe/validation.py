"""Startup validation for the Fake Solis Probe configuration."""

from __future__ import annotations

from . import config, event_log, home_assistant


def validate_config() -> bool:
    """Validate all required configuration options at startup. Returns True if OK."""
    errors: list[str] = []

    # Check sensor entity IDs are non-empty.
    sensor_map: dict[str, str] = {}
    for key in config.SENSOR_KEYS:
        entity_id = str(config.OPTIONS.get(key, "")).strip()
        if not entity_id:
            errors.append(f"Option '{key}' is empty — must be a valid HA entity ID")
        elif not entity_id.startswith("sensor."):
            errors.append(
                f"Option '{key}' = '{entity_id}' — expected entity starting with 'sensor.'"
            )
        else:
            sensor_map[key] = entity_id

    # Check grid_power_sign_convention.
    sign_convention = str(config.OPTIONS.get("grid_power_sign_convention", "")).strip()
    if sign_convention not in ("negate", "direct"):
        errors.append(
            "Option 'grid_power_sign_convention' = "
            f"'{sign_convention}' — must be 'negate' or 'direct'"
        )

    # Check scaling factors are positive numbers.
    for scale_key in (
        "pv_power_scale",
        "grid_power_scale",
        "total_energy_scale",
        "daily_energy_scale",
    ):
        try:
            value = float(config.OPTIONS.get(scale_key, 0))
            if value <= 0:
                errors.append(f"Option '{scale_key}' = {value} — must be > 0")
        except (ValueError, TypeError):
            errors.append(
                f"Option '{scale_key}' = "
                f"'{config.OPTIONS.get(scale_key)}' — must be a number"
            )

    # If basic validation passed, verify entities exist in Home Assistant.
    if not errors:
        event_log.log_event("config_validating_entities", entities=sensor_map)
        for key, entity_id in sensor_map.items():
            ok, message = home_assistant.ha_api_check_entity(entity_id)
            if ok:
                event_log.log_event(
                    "config_entity_ok", key=key, entity_id=entity_id, detail=message
                )
            else:
                errors.append(
                    f"Option '{key}' = '{entity_id}' — "
                    f"entity not found in HA: {message}"
                )

    if errors:
        event_log.log_event("config_validation_failed", errors=errors)
        for error in errors:
            print(f"[FATAL] {error}", flush=True)
        return False

    event_log.log_event(
        "config_validation_passed",
        sensors=sensor_map,
        sign_convention=sign_convention,
    )
    return True
