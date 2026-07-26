"""Home Assistant Supervisor API access."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def ha_api_check_entity(entity_id: str) -> tuple[bool, str]:
    """Check whether an entity exists in HA. Returns ``(ok, message)``."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False, "SUPERVISOR_TOKEN not set"
    url = (
        f"http://supervisor/core/api/states/{urllib.parse.quote(entity_id, safe='._-')}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data: Any = json.loads(response.read().decode())
        state = data.get("state", "") if isinstance(data, dict) else ""
        unit = ""
        if isinstance(data, dict) and isinstance(data.get("attributes"), dict):
            unit = data["attributes"].get("unit_of_measurement", "")
        return True, f"state={state}, unit={unit}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, "Entity not found (404)"
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def ha_api_get_state(entity_id: str) -> float | None:
    """Read a sensor state from HA Core API. Returns float or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    url = (
        f"http://supervisor/core/api/states/{urllib.parse.quote(entity_id, safe='._-')}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data: Any = json.loads(response.read().decode())
        state = data.get("state") if isinstance(data, dict) else None
        if state in (None, "unavailable", "unknown", ""):
            return None
        return float(state)
    except (ValueError, TypeError):
        return None
    except Exception:
        # Don't log here — the caller handles backoff logging.
        return None
