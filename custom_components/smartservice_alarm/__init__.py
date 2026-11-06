"""Smart Service Alarm: alarm panel with per-user PINs."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.auth import EVENT_USER_REMOVED
from homeassistant.auth.models import User
from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from . import events, websocket
from .actions import (
    AlarmConfigEntry,
    async_clear_pin_for,
    async_entry_for,
    async_set_pin_for,
    async_target_user,
    checked_caller,
    entity_id_of,
)
from .const import (
    ACTION_UNLOCK,
    ATTR_CURRENT_PIN,
    ATTR_PIN,
    ATTR_SENSOR,
    ATTR_USER_ID,
    DOMAIN,
    SERVICE_CLEAR_PIN,
    SERVICE_SET_PIN,
    SERVICE_STATUS,
    SERVICE_TRIGGER,
    SERVICE_UNLOCK,
)
from .pins import NO_ACCOUNT, PinManager, pins_only

PLATFORMS = [Platform.ALARM_CONTROL_PANEL]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

__all__ = ["AlarmConfigEntry"]

_TARGET = {vol.Optional(ATTR_ENTITY_ID): cv.entity_id}
SET_PIN_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Required(ATTR_USER_ID): cv.string,
        vol.Required(ATTR_PIN): cv.string,
        vol.Optional(ATTR_CURRENT_PIN): cv.string,
    }
)
USER_SCHEMA = vol.Schema({**_TARGET, vol.Required(ATTR_USER_ID): cv.string})
STATUS_SCHEMA = vol.Schema(_TARGET)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions and its websocket command."""
    _async_register_services(hass)
    websocket.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AlarmConfigEntry) -> bool:
    """Load PINs, lockouts and panel state of one alarm."""
    manager = PinManager(hass, entry.entry_id)
    await manager.async_load()
    known = {user.id for user in await hass.auth.async_get_users()}
    if manager.remove_unknown_users(known):
        await manager.async_save()
    entry.runtime_data = manager

    async def _async_user_removed(event: Event) -> None:
        if manager.remove_unknown_users(
            {user.id for user in await hass.auth.async_get_users()}
        ):
            await manager.async_save()

    entry.async_on_unload(hass.bus.async_listen(EVENT_USER_REMOVED, _async_user_removed))
    if not pins_only(entry.data):
        # An entry with only PINs has no alarm panel: nothing to arm, no
        # sensors, no countdowns - the PIN check, the PINs and the lockouts.
        manager.platforms = list(PLATFORMS)
        await hass.config_entries.async_forward_entry_setups(entry, manager.platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlarmConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(
        entry, entry.runtime_data.platforms
    )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the storage file with PIN hashes together with the entry."""
    await PinManager(hass, entry.entry_id).async_remove()


async def _async_caller(hass: HomeAssistant, call: ServiceCall, *, admin: bool) -> User:
    """The signed-in user who called the action; refuse calls without one."""
    user_id = call.context.user_id
    user = await hass.auth.async_get_user(user_id) if user_id else None
    return checked_caller(user, admin=admin)


@callback
def _async_entry(hass: HomeAssistant, call: ServiceCall) -> AlarmConfigEntry:
    """Alarm entry addressed by the call (entity_id or the only one)."""
    return async_entry_for(hass, call.data.get(ATTR_ENTITY_ID))


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    async def async_set_pin(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=False)
        await async_set_pin_for(
            hass,
            _async_entry(hass, call),
            caller,
            call.data[ATTR_USER_ID],
            call.data[ATTR_PIN],
            call.data.get(ATTR_CURRENT_PIN),
            call.context,
        )

    async def async_clear_pin(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=True)
        await async_clear_pin_for(
            hass, _async_entry(hass, call), caller, call.data[ATTR_USER_ID], call.context
        )

    async def async_unlock(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=True)
        entry = _async_entry(hass, call)
        target_id: str = call.data[ATTR_USER_ID]
        if target_id != NO_ACCOUNT:
            await async_target_user(hass, target_id)
        if await entry.runtime_data.async_unlock(target_id):
            await events.async_fire(
                hass,
                entity_id_of(hass, entry),
                ACTION_UNLOCK,
                call.context,
                caller_id=caller.id,
                subject_id=None if target_id == NO_ACCOUNT else target_id,
            )

    async def async_status(call: ServiceCall) -> ServiceResponse:
        await _async_caller(hass, call, admin=True)
        manager = _async_entry(hass, call).runtime_data
        response: dict[str, Any] = {}
        users = [u for u in await hass.auth.async_get_users() if not u.system_generated]
        ids = [user.id for user in users]
        if manager.locked_until(NO_ACCOUNT) is not None:
            ids.append(NO_ACCOUNT)
        for user_id in ids:
            until = manager.locked_until(user_id)
            response[user_id] = {
                "pin": manager.has_pin(user_id),
                "zablokowany_do": until.isoformat() if until else None,
            }
        return response

    hass.services.async_register(DOMAIN, SERVICE_SET_PIN, async_set_pin, SET_PIN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_PIN, async_clear_pin, USER_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNLOCK, async_unlock, USER_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_STATUS,
        async_status,
        STATUS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_TRIGGER,
        entity_domain=ALARM_DOMAIN,
        schema={vol.Optional(ATTR_SENSOR): cv.string},
        func="async_trigger_sensor",
    )
