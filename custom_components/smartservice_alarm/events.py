"""Events and logbook texts of Smart Service Alarm (never any PIN)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_ARM,
    ACTION_DISARM,
    ACTION_LOCKOUT,
    ACTION_PIN_CLEARED,
    ACTION_PIN_SET,
    ACTION_TRIGGER,
    ACTION_UNLOCK,
    ACTION_WRONG_CODE,
    EVENT_ALARM,
)

MODE_NAMES = {
    "pl": {
        "armed_away": "poza domem",
        "armed_home": "w domu",
        "armed_night": "noc",
    },
    "en": {
        "armed_away": "away",
        "armed_home": "home",
        "armed_night": "night",
    },
}


async def async_user_name(hass: HomeAssistant, user_id: str | None) -> str | None:
    """Display name of a Home Assistant user."""
    if not user_id:
        return None
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        return None
    return user.name or user_id


async def async_fire(
    hass: HomeAssistant,
    entity_id: str | None,
    action: str,
    context: Context | None,
    *,
    owner_id: str | None = None,
    caller_id: str | None = None,
    subject_id: str | None = None,
    **extra: Any,
) -> None:
    """Fire smartservice_alarm_event with names, never with a PIN."""
    data: dict[str, Any] = {"entity_id": entity_id, "akcja": action}
    for prefix, user_id in (
        ("wlasciciel", owner_id),
        ("konto", caller_id),
        ("dotyczy", subject_id),
    ):
        if user_id:
            data[f"{prefix}_id"] = user_id
            data[prefix] = await async_user_name(hass, user_id)
    data.update({key: value for key, value in extra.items() if value is not None})
    hass.bus.async_fire(EVENT_ALARM, data, context=context)


def _local_time(value: str | None) -> str:
    moment = dt_util.parse_datetime(value) if value else None
    if moment is None:
        return "?"
    return dt_util.as_local(moment).strftime("%H:%M")


def describe(data: dict[str, Any], language: str | None) -> str:
    """Logbook text of one smartservice_alarm_event."""
    polish = (language or "").lower().startswith("pl")
    names = MODE_NAMES["pl" if polish else "en"]
    action = data.get("akcja")
    owner = data.get("wlasciciel")
    caller = data.get("konto")
    automation = "Automatyzacja" if polish else "Automation"
    no_account = "bez konta" if polish else "no account"
    who = owner or caller or automation
    if owner and caller and caller != owner:
        who += f" (z konta: {caller})" if polish else f" (from account: {caller})"
    mode = names.get(data.get("tryb") or "", data.get("tryb") or "")

    if action == ACTION_ARM:
        return f"Uzbrojenie ({mode}): {who}" if polish else f"Armed ({mode}): {who}"
    if action == ACTION_DISARM:
        return f"Rozbrojenie: {who}" if polish else f"Disarmed: {who}"
    if action == ACTION_WRONG_CODE:
        tries = f"{data.get('proby', '?')}/{data.get('limit', '?')}"
        account = caller or no_account
        if polish:
            return f"Błędny PIN z konta {account} ({tries})"
        return f"Wrong PIN from account {account} ({tries})"
    if action == ACTION_LOCKOUT:
        account = caller or no_account
        until = _local_time(data.get("do"))
        if polish:
            return f"Blokada konta {account} do {until}"
        return f"Account {account} locked until {until}"
    if action == ACTION_UNLOCK:
        subject = data.get("dotyczy") or no_account
        if polish:
            return f"Odblokowanie konta {subject} (przez: {caller})"
        return f"Account {subject} unlocked (by: {caller})"
    if action == ACTION_TRIGGER:
        sensor = data.get("czujnik")
        if sensor:
            return f"Alarm: {sensor}"
        return "Alarm: wyzwolenie" if polish else "Alarm: triggered"
    if action == ACTION_PIN_SET:
        return f"PIN ustawiony: {who}" if polish else f"PIN set: {who}"
    if action == ACTION_PIN_CLEARED:
        return f"PIN usunięty: {who}" if polish else f"PIN removed: {who}"
    return str(action)
