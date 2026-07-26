"""Home Assistant sensor polling loop."""

from __future__ import annotations

import time

from . import config, event_log, home_assistant, sensor_cache, telemetry


def sensor_poll_loop() -> None:
    """Background thread: poll HA sensors every five seconds, update registers."""
    entity_ids = [str(config.OPTIONS.get(key, "")) for key in config.SENSOR_KEYS]
    entity_ids = [entity_id for entity_id in entity_ids if entity_id]

    # Initialize cache.
    with sensor_cache.CACHE_LOCK:
        for entity_id in entity_ids:
            if entity_id not in sensor_cache.SENSOR_CACHE:
                sensor_cache.SENSOR_CACHE[entity_id] = None

    event_log.log_event("sensor_poll_started", sensors=entity_ids)
    poll_counter = 0

    while True:
        for entity_id in entity_ids:
            value = home_assistant.ha_api_get_state(entity_id)

            if value is not None:
                # Success — update both caches under a single lock.
                with sensor_cache.CACHE_LOCK:
                    sensor_cache.SENSOR_CACHE[entity_id] = value  # current reading
                    sensor_cache.LAST_KNOWN_CACHE[entity_id] = (
                        value  # retain last-known
                    )
                    sensor_cache.SENSOR_ERROR_COUNT[entity_id] = 0
                # Fallback counters reset in update_live_registers when raw is not None.
            else:
                # Failed — mark the current reading as None so apply_behavior()
                # receives raw=None and applies the configured fallback.
                # LAST_KNOWN_CACHE is intentionally NOT updated here.
                with sensor_cache.CACHE_LOCK:
                    count = sensor_cache.SENSOR_ERROR_COUNT.get(entity_id, 0) + 1
                    sensor_cache.SENSOR_ERROR_COUNT[entity_id] = count
                    sensor_cache.SENSOR_CACHE[entity_id] = None  # v0.5.1 fix
                    last_known = sensor_cache.LAST_KNOWN_CACHE.get(entity_id)
                if count == 1 or count % config.ERROR_LOG_INTERVAL == 0:
                    event_log.log_event(
                        "sensor_unavailable",
                        entity_id=entity_id,
                        consecutive_errors=count,
                        last_known_value=last_known,
                    )

        telemetry.update_live_registers()

        # Log current values periodically (every ~60 seconds = 12 cycles).
        poll_counter += 1
        if poll_counter % 12 == 1:
            with sensor_cache.CACHE_LOCK:
                snapshot = dict(sensor_cache.SENSOR_CACHE)
            event_log.log_event("sensor_poll_values", values=snapshot)

        time.sleep(5)
