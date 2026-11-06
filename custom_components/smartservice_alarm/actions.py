"""What the actions and the websocket commands share: who called, which alarm,
and the PIN changes. One code path, so both ways have the same rules."""

from __future__ import annotations

from homeassistant.auth.models import User
from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import events
from .const import ACTION_PIN_CLEARED, ACTION_PIN_SET, DOMAIN
from .pins import PinManager, alarm_error

type AlarmConfigEntry = ConfigEntry[PinManager]


def checked_caller(user: User | None, *, admin: bool) -> User:
    """The signed-in user who called; refuse calls without one."""
    if user is None:
        raise alarm_error("user_required")
    if admin and not user.is_admin:
        raise alarm_error("admin_required")
    return user


@callback
def async_entry_for(hass: HomeAssistant, entity_id: str | None) -> AlarmConfigEntry:
    """Alarm entry of the entity_id, or the only one."""
    entries = {
        entry.entry_id: entry for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    }
    if entity_id is not None:
        registry_entry = er.async_get(hass).async_get(entity_id)
        if (
            registry_entry is None
            or registry_entry.platform != DOMAIN
            or registry_entry.config_entry_id not in entries
        ):
            raise alarm_error("unknown_alarm")
        return entries[registry_entry.config_entry_id]
    if len(entries) == 1:
        return next(iter(entries.values()))
    if not entries:
        raise alarm_error("unknown_alarm")
    raise alarm_error("choose_alarm")


def entity_id_of(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    return er.async_get(hass).async_get_entity_id(ALARM_DOMAIN, DOMAIN, entry.entry_id)


async def async_target_user(hass: HomeAssistant, user_id: str) -> User:
    user = await hass.auth.async_get_user(user_id)
    if user is None or user.system_generated:
        raise alarm_error("unknown_user")
    return user


async def async_set_pin_for(
    hass: HomeAssistant,
    entry: AlarmConfigEntry,
    caller: User,
    target_id: str,
    pin: str,
    current_pin: str | None,
    context: Context | None,
) -> None:
    """Set a PIN: an administrator for anyone, a user only for himself."""
    if not caller.is_admin and target_id != caller.id:
        raise alarm_error("own_pin_only")
    await async_target_user(hass, target_id)
    await entry.runtime_data.async_set_pin(
        target_id,
        pin,
        admin=caller.is_admin,
        bucket=caller.id,
        current_pin=current_pin,
        context=context,
    )
    await events.async_fire(
        hass,
        entity_id_of(hass, entry),
        ACTION_PIN_SET,
        context,
        owner_id=target_id,
        caller_id=caller.id,
    )


async def async_clear_pin_for(
    hass: HomeAssistant,
    entry: AlarmConfigEntry,
    caller: User,
    target_id: str,
    context: Context | None,
) -> bool:
    """Remove a PIN (the caller is an administrator); True when there was one."""
    if not await entry.runtime_data.async_clear_pin(target_id):
        return False
    await events.async_fire(
        hass,
        entity_id_of(hass, entry),
        ACTION_PIN_CLEARED,
        context,
        owner_id=target_id,
        caller_id=caller.id,
    )
    return True
