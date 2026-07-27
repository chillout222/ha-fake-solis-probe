"""Thread-safe ownership of Home Assistant sensor caches."""

from __future__ import annotations

import threading
from typing import Optional


# Current sensor reading — explicitly None when a sensor is unavailable,
# unknown, or in error. This is what telemetry.apply_behavior() receives as
# ``raw``. Set it to None on every failed poll.
SENSOR_CACHE: dict[str, Optional[float]] = {}

# Last successful numeric reading per entity. Retained across unavailable
# periods; used by ``last_known`` behavior logging.
LAST_KNOWN_CACHE: dict[str, Optional[float]] = {}

CACHE_LOCK = threading.Lock()

# Error backoff tracking: entity_id -> consecutive_error_count
SENSOR_ERROR_COUNT: dict[str, int] = {}


def reset() -> None:
    """Clear all cache and backoff state for an isolated test or fresh runtime."""
    with CACHE_LOCK:
        SENSOR_CACHE.clear()
        LAST_KNOWN_CACHE.clear()
        SENSOR_ERROR_COUNT.clear()


def reset_caches() -> None:
    """Compatibility-friendly name for resetting all sensor cache state."""
    reset()
