"""Logbook descriptions of Smart Service Alarm events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_ALARM
from .events import describe


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe smartservice_alarm_event for the logbook."""

    @callback
    def async_describe_alarm_event(event: Event) -> dict[str, Any]:
        entity_id = event.data.get("entity_id")
        state = hass.states.get(entity_id) if entity_id else None
        description: dict[str, Any] = {
            LOGBOOK_ENTRY_NAME: state.name if state else "Smart Service Alarm",
            LOGBOOK_ENTRY_MESSAGE: describe(dict(event.data), hass.config.language),
        }
        if entity_id:
            description[LOGBOOK_ENTRY_ENTITY_ID] = entity_id
        return description

    async_describe_event(DOMAIN, EVENT_ALARM, async_describe_alarm_event)
