"""Events and logbook texts of Smart Service Alarm (never any PIN)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_ARM,
    ACTION_ARM_REFUSED,
    ACTION_BACK,
    ACTION_DISARM,
    ACTION_LOCKOUT,
    ACTION_OPTIONS,
    ACTION_PIN_CLEARED,
    ACTION_PIN_SET,
    ACTION_SENSOR_BYPASSED,
    ACTION_TRIGGER,
    ACTION_UNLOCK,
    ACTION_WRONG_CODE,
    EVENT_ALARM,
)

# Z17: the options' names in the logbook.
OPTION_NAMES = {
    "pl": {
        "arm_away": "tryb poza domem",
        "arm_home": "tryb w domu",
        "arm_night": "tryb nocny",
        "exit_delay": "czas na wyjście",
        "entry_delay": "czas zwłoki",
        "trigger_time": "czas trwania alarmu",
        "code_arm_required": "PIN przy uzbrajaniu",
        "sensors": "czujniki sprawdzane przy uzbrojeniu",
    },
    "en": {
        "arm_away": "away mode",
        "arm_home": "home mode",
        "arm_night": "night mode",
        "exit_delay": "exit delay",
        "entry_delay": "entry delay",
        "trigger_time": "alarm duration",
        "code_arm_required": "PIN for arming",
        "sensors": "sensors checked when arming",
    },
}

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
    if action == ACTION_ARM_REFUSED:
        opened = ", ".join(data.get("otwarte") or [])
        missing = ", ".join(data.get("brak_odczytu") or [])
        if polish:
            parts = [
                f"Zamknij: {opened}" if opened else "",
                f"Brak odczytu: {missing}" if missing else "",
            ]
            return "Nieuzbrojony po czasie na wyjście — " + ". ".join(p for p in parts if p)
        parts = [
            f"Close: {opened}" if opened else "",
            f"No reading: {missing}" if missing else "",
        ]
        return "Not armed after the exit delay — " + ". ".join(p for p in parts if p)
    if action == ACTION_OPTIONS:
        option_names = OPTION_NAMES["pl" if polish else "en"]
        changed = ", ".join(option_names.get(k, k) for k in data.get("zmienione") or [])
        if polish:
            return f"Ustawienia alarmu zmienione: {changed}"
        return f"Alarm settings changed: {changed}"
    if action == ACTION_PIN_CLEARED:
        return f"PIN usunięty: {who}" if polish else f"PIN removed: {who}"
    if action == ACTION_SENSOR_BYPASSED:
        sensor = data.get("czujnik") or "?"
        count = data.get("wyzwolenia", "?")
        if polish:
            return f"Czujka pominięta do rozbrojenia: {sensor} ({count} alarmy z rzędu)"
        return f"Sensor bypassed until disarming: {sensor} ({count} alarms in a row)"
    if action == ACTION_BACK:
        minutes = data.get("przerwa_min")
        if polish:
            if minutes:
                return f"Alarm wrócił po {minutes} min przerwy"
            return "Alarm wrócił po przerwie"
        if minutes:
            return f"Alarm back after a {minutes} min break"
        return "Alarm back after a break"
    return str(action)
