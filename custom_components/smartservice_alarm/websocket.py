"""Websocket commands of Smart Service Alarm: everything that carries a PIN.

Home Assistant puts the data of every action (service) call into a
call_service event, and the recorder writes that event to its database. A
websocket command's data goes into no event, so a PIN sent this way never
reaches the database. The rules are the same as with the actions: the same
entity methods, permissions, counters and lockouts.

No schema refuses a PIN field: Home Assistant logs a refused websocket
message together with the refused value. A value that is not text (or a
number) is checked as given and so is just a wrong PIN.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
)
from homeassistant.components.alarm_control_panel.const import DATA_COMPONENT
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .actions import (
    AlarmConfigEntry,
    async_clear_pin_for,
    async_entry_for,
    async_set_pin_for,
    checked_caller,
    entity_id_of,
)
from .const import (
    ATTR_CURRENT_PIN,
    ATTR_PIN,
    ATTR_USER_ID,
    WS_ARM,
    WS_CHECK_PIN,
    WS_CLEAR_PIN,
    WS_DISARM,
    WS_SET_PIN,
)
from .pins import alarm_error

# The panel's modes and the entity method of each one (as the service calls it).
ARM_MODES = {
    "away": "async_handle_alarm_arm_away",
    "home": "async_handle_alarm_arm_home",
    "night": "async_handle_alarm_arm_night",
}
DONE = {"wynik": "ok"}


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (
        websocket_check_pin,
        websocket_arm,
        websocket_disarm,
        websocket_set_pin,
        websocket_clear_pin,
    ):
        websocket_api.async_register_command(hass, handler)


def as_pin(value: Any) -> str:
    """A PIN as text; any other value becomes a PIN nobody has."""
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _optional_pin(value: Any) -> str | None:
    return None if value is None else as_pin(value)


def _text(value: Any, key: str) -> str:
    """A field that must be text (a user id, an entity id)."""
    if not isinstance(value, str):
        raise alarm_error(key)
    return value


def _entry(hass: HomeAssistant, msg: dict[str, Any]) -> AlarmConfigEntry:
    entity_id = msg.get(ATTR_ENTITY_ID)
    return async_entry_for(
        hass, None if entity_id is None else _text(entity_id, "unknown_alarm")
    )


def _send_error(
    connection: websocket_api.ActiveConnection, msg_id: int, err: HomeAssistantError
) -> None:
    """The error as the actions give it: a translation key and placeholders."""
    if isinstance(err, Unauthorized):
        connection.send_error(msg_id, websocket_api.ERR_UNAUTHORIZED, "Unauthorized")
        return
    key = err.translation_key or websocket_api.ERR_HOME_ASSISTANT_ERROR
    connection.send_error(
        msg_id,
        key,
        str(err) or key,
        translation_key=err.translation_key,
        translation_domain=err.translation_domain,
        translation_placeholders=err.translation_placeholders,
    )


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

    Nothing changes in the alarm; wrong PINs count together with arming. A
    wrong PIN or a lockout is a result, not an error.
    """
    try:
        entry = _entry(hass, msg)
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    result = await entry.runtime_data.async_check_entry(
        connection.user.id, as_pin(msg["pin"]), connection.context(msg)
    )
    connection.send_result(msg["id"], result.as_response())


async def _async_panel_call(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    method: str,
) -> None:
    """Call the panel's own method exactly as its service would."""
    try:
        entry = _entry(hass, msg)
        entity_id = entity_id_of(hass, entry)
        entity: AlarmControlPanelEntity | None = (
            hass.data[DATA_COMPONENT].get_entity(entity_id) if entity_id else None
        )
        if entity_id is None or entity is None:
            raise alarm_error("unknown_alarm")
        if not connection.user.permissions.check_entity(entity_id, POLICY_CONTROL):
            raise Unauthorized(
                context=connection.context(msg),
                entity_id=entity_id,
                permission=POLICY_CONTROL,
            )
        entity.async_set_context(connection.context(msg))
        await getattr(entity, method)(_optional_pin(msg.get("code")))
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], DONE)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_ARM,
        # The mode is no secret: a refused mode may be logged.
        vol.Required("tryb"): vol.In(list(ARM_MODES)),
        vol.Optional("code"): object,
        vol.Optional(ATTR_ENTITY_ID): object,
    }
)
@websocket_api.async_response
async def websocket_arm(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Arm with a PIN (alarm_control_panel.alarm_arm_* without its event)."""
    await _async_panel_call(hass, connection, msg, ARM_MODES[msg["tryb"]])


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_DISARM,
        vol.Optional("code"): object,
        vol.Optional(ATTR_ENTITY_ID): object,
    }
)
@websocket_api.async_response
async def websocket_disarm(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Disarm with a PIN (alarm_control_panel.alarm_disarm without its event)."""
    await _async_panel_call(hass, connection, msg, "async_handle_alarm_disarm")


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SET_PIN,
        vol.Required(ATTR_USER_ID): object,
        vol.Required(ATTR_PIN): object,
        vol.Optional(ATTR_CURRENT_PIN): object,
        vol.Optional(ATTR_ENTITY_ID): object,
    }
)
@websocket_api.async_response
async def websocket_set_pin(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """smartservice_alarm.set_pin without its event."""
    try:
        await async_set_pin_for(
            hass,
            _entry(hass, msg),
            checked_caller(connection.user, admin=False),
            _text(msg[ATTR_USER_ID], "unknown_user"),
            as_pin(msg[ATTR_PIN]),
            _optional_pin(msg.get(ATTR_CURRENT_PIN)),
            connection.context(msg),
        )
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], DONE)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CLEAR_PIN,
        vol.Required(ATTR_USER_ID): object,
        vol.Optional(ATTR_ENTITY_ID): object,
    }
)
@websocket_api.async_response
async def websocket_clear_pin(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """smartservice_alarm.clear_pin, the same way as the other PIN commands."""
    try:
        removed = await async_clear_pin_for(
            hass,
            _entry(hass, msg),
            checked_caller(connection.user, admin=True),
            _text(msg[ATTR_USER_ID], "unknown_user"),
            connection.context(msg),
        )
    except HomeAssistantError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {**DONE, "usuniety": removed})
