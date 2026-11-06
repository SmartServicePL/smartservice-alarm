"""Smart Service Alarm: alarm panel with per-user PINs."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.auth import EVENT_USER_REMOVED
from homeassistant.auth.models import User
from homeassistant.components import websocket_api
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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from . import events
from .const import (
    ACTION_PIN_CLEARED,
    ACTION_PIN_SET,
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
    WS_CHECK_PIN,
)
from .pins import NO_ACCOUNT, PinManager, alarm_error

PLATFORMS = [Platform.ALARM_CONTROL_PANEL]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AlarmConfigEntry = ConfigEntry[PinManager]

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
    websocket_api.async_register_command(hass, websocket_check_pin)
    return True


def _entry_pin(value: Any) -> str:
    """The PIN as text.

    Any other value is checked as given and so counts as a wrong PIN. The
    schema itself never refuses it, because Home Assistant logs a refused
    websocket message together with the refused value.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CHECK_PIN,
        vol.Required("pin"): object,
        vol.Optional(ATTR_ENTITY_ID): object,
    }
)
@websocket_api.async_response
async def websocket_check_pin(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """PIN check at the entry to the panel's "Security" view.

    A websocket command, not a service: a service call's data goes into a
    call_service event and so into the recorder's database. Nothing here
    changes the alarm; wrong PINs count together with arming.
    """
    entity_id = msg.get(ATTR_ENTITY_ID)
    try:
        if entity_id is not None and not isinstance(entity_id, str):
            raise alarm_error("unknown_alarm")
        entry = _async_entry_for(hass, entity_id)
    except ServiceValidationError as err:
        key = err.translation_key or "unknown_alarm"
        connection.send_error(msg["id"], key, key)
        return
    result = await entry.runtime_data.async_check_entry(
        connection.user.id, _entry_pin(msg["pin"]), connection.context(msg)
    )
    connection.send_result(msg["id"], result.as_response())


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlarmConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the storage file with PIN hashes together with the entry."""
    await PinManager(hass, entry.entry_id).async_remove()


async def _async_caller(hass: HomeAssistant, call: ServiceCall, *, admin: bool) -> User:
    """The signed-in user who called the action; refuse calls without one."""
    user_id = call.context.user_id
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None:
        raise alarm_error("user_required")
    if admin and not user.is_admin:
        raise alarm_error("admin_required")
    return user


@callback
def _async_entry(hass: HomeAssistant, call: ServiceCall) -> AlarmConfigEntry:
    """Alarm entry addressed by the call (entity_id or the only one)."""
    return _async_entry_for(hass, call.data.get(ATTR_ENTITY_ID))


@callback
def _async_entry_for(hass: HomeAssistant, entity_id: str | None) -> AlarmConfigEntry:
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


async def _async_target_user(hass: HomeAssistant, user_id: str) -> User:
    user = await hass.auth.async_get_user(user_id)
    if user is None or user.system_generated:
        raise alarm_error("unknown_user")
    return user


def _entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    return er.async_get(hass).async_get_entity_id(ALARM_DOMAIN, DOMAIN, entry.entry_id)


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    async def async_set_pin(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=False)
        entry = _async_entry(hass, call)
        target_id: str = call.data[ATTR_USER_ID]
        if not caller.is_admin and target_id != caller.id:
            raise alarm_error("own_pin_only")
        await _async_target_user(hass, target_id)
        await entry.runtime_data.async_set_pin(
            target_id,
            call.data[ATTR_PIN],
            admin=caller.is_admin,
            bucket=caller.id,
            current_pin=call.data.get(ATTR_CURRENT_PIN),
            context=call.context,
        )
        await events.async_fire(
            hass,
            _entity_id(hass, entry),
            ACTION_PIN_SET,
            call.context,
            owner_id=target_id,
            caller_id=caller.id,
        )

    async def async_clear_pin(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=True)
        entry = _async_entry(hass, call)
        target_id: str = call.data[ATTR_USER_ID]
        if await entry.runtime_data.async_clear_pin(target_id):
            await events.async_fire(
                hass,
                _entity_id(hass, entry),
                ACTION_PIN_CLEARED,
                call.context,
                owner_id=target_id,
                caller_id=caller.id,
            )

    async def async_unlock(call: ServiceCall) -> None:
        caller = await _async_caller(hass, call, admin=True)
        entry = _async_entry(hass, call)
        target_id: str = call.data[ATTR_USER_ID]
        if target_id != NO_ACCOUNT:
            await _async_target_user(hass, target_id)
        if await entry.runtime_data.async_unlock(target_id):
            await events.async_fire(
                hass,
                _entity_id(hass, entry),
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
