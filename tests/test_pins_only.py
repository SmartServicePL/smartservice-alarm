"""1.4.0: wpis „same PIN-y” — PIN do widoku w panelu w domu bez tego alarmu.

Widok w panelu zawsze pyta o PIN, także w domu bez alarmu. Wpis
bez centrali alarmu: sprawdzenie PIN-u, PIN-y i blokady jak zawsze, nic do
uzbrajania. Centralę można włączyć później w opcjach; PIN-y zostają.
"""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from homeassistant import config_entries
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.smartservice_alarm.const import (
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_ALARM,
    WS_ARM,
    WS_CHECK_PIN,
    WS_SET_PIN,
)
from custom_components.smartservice_alarm.events import describe

from .conftest import ENTITY, alarm, give_pins, make_entry, service

WRONG = "4826"


async def _client(hass: HomeAssistant, hass_ws_client, user: MockUser):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _send(client, kind: str, **fields: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": kind, **fields})
    return await client.receive_json()


async def _create(hass: HomeAssistant, kind: str = "piny") -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    if result["type"] is not FlowResultType.FORM:
        return result
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Dom", "rodzaj": kind}
    )
    await hass.async_block_till_done()
    return result


def _panels(hass: HomeAssistant) -> list[str]:
    return [
        item.entity_id
        for item in er.async_get(hass).entities.values()
        if item.platform == DOMAIN
    ]


async def test_pins_only_entry_has_no_alarm_panel(hass, users) -> None:
    result = await _create(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"name": "Dom", "rodzaj": "piny"}
    assert result["options"] == {}
    assert hass.states.get(ENTITY) is None
    assert _panels(hass) == []


async def test_pins_and_the_entry_check_work_the_same(hass, users, hass_ws_client) -> None:
    await _create(hass)
    pins = await give_pins(hass, users)
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    client = await _client(hass, hass_ws_client, users.piotr)

    right = await _send(client, WS_CHECK_PIN, pin=pins["piotr"])
    assert right["result"] == {"wynik": "poprawny", "user_id": users.piotr.id, "osoba": "Piotr"}
    for left in (4, 3, 2, 1):
        assert (await _send(client, WS_CHECK_PIN, pin=WRONG))["result"] == {
            "wynik": "niepoprawny",
            "pozostalo": left,
        }
    assert (await _send(client, WS_CHECK_PIN, pin=WRONG))["result"]["wynik"] == "zablokowany"

    await hass.async_block_till_done()
    assert found[-6].data["entity_id"] is None
    assert describe(dict(found[-7].data), "pl") == "Piotr: wejście do Bezpieczeństwa"
    assert describe(dict(found[-1].data), "pl").startswith("Blokada konta Piotr do ")
    status = await service(hass, "status", users.admin, response=True)
    assert status[users.piotr.id]["pin"] is True
    assert status[users.piotr.id]["zablokowany_do"] is not None


async def test_no_pins_yet_counts_nothing(hass, users, hass_ws_client, scrypt_calls) -> None:
    """No PIN set yet: brak_pinow, no try counted, no lock, no event."""
    await _create(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    client = await _client(hass, hass_ws_client, users.piotr)

    for _ in range(7):
        answer = await _send(client, WS_CHECK_PIN, pin=WRONG)
        assert answer["result"] == {"wynik": "brak_pinow"}
    await hass.async_block_till_done()
    assert found == []
    assert entry.runtime_data.lockouts == {}
    assert scrypt_calls.calls == 0

    # The first PIN set: the usual answers from then on.
    pins = await give_pins(hass, users)
    assert (await _send(client, WS_CHECK_PIN, pin=WRONG))["result"] == {
        "wynik": "niepoprawny",
        "pozostalo": 4,
    }
    assert (await _send(client, WS_CHECK_PIN, pin=pins["piotr"]))["result"]["wynik"] == (
        "poprawny"
    )


async def test_no_pins_on_a_panel_too(hass, users, hass_ws_client) -> None:
    make_entry(hass)
    assert await hass.config_entries.async_setup(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    await hass.async_block_till_done()
    client = await _client(hass, hass_ws_client, users.adam)
    assert (await _send(client, WS_CHECK_PIN, pin=WRONG))["result"] == {"wynik": "brak_pinow"}


async def test_nothing_to_arm(hass, users, hass_ws_client) -> None:
    await _create(hass)
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    answer = await _send(client, WS_ARM, tryb="away", code=pins["piotr"])
    assert answer["error"]["code"] == "unknown_alarm"
    # A user changes his own PIN as always.
    changed = await _send(
        client, WS_SET_PIN, user_id=users.piotr.id, pin="3579", current_pin=pins["piotr"]
    )
    assert changed["result"] == {"wynik": "ok"}


async def test_one_place_for_the_pins(hass, users) -> None:
    await _create(hass)
    assert (await _create(hass, "centrala"))["reason"] == "pins_only_exists"
    assert (await _create(hass, "piny"))["reason"] == "pins_only_exists"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_a_panel_already_keeps_the_pins(hass, users) -> None:
    make_entry(hass)
    result = await _create(hass, "piny")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "panel_keeps_pins"
    # A second panel stays possible, as before.
    assert (await _create(hass, "centrala"))["type"] is FlowResultType.CREATE_ENTRY


async def test_the_panel_turned_on_later_keeps_the_pins(hass, users) -> None:
    await _create(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    pins = await give_pins(hass, users)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "piny"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"centrala": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY) is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"centrala": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data == {"name": "Dom"}
    assert entry.options == DEFAULT_OPTIONS
    assert hass.states.get(ENTITY).state == "disarmed"
    # The PINs set before are the panel's PINs now.
    await alarm(hass, "alarm_arm_home", users.piotr, pins["piotr"])
    assert hass.states.get(ENTITY).attributes["changed_by"] == "Piotr"
    # Now the panel's options form, as for any panel.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"


async def test_unload_and_remove(hass, users) -> None:
    await _create(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_remove(entry.entry_id)
    assert hass.config_entries.async_entries(DOMAIN) == []
