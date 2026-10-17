"""Diagnostics of Smart Service Alarm without salts or hashes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .pins import PinManager

TO_REDACT = {"salt", "hash"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Options, panel state, PIN metadata and lockouts; secrets redacted."""
    manager: PinManager = entry.runtime_data
    return {
        "options": dict(entry.options),
        "stan": deepcopy(manager.state),
        "piny": async_redact_data(deepcopy(manager.pins), TO_REDACT),
        "blokady": deepcopy(manager.lockouts),
    }
