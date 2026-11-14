"""1.4.1: the first PIN comes from an administrator.

Every PIN disarms the panel. Before 1.4.1 an account without a PIN (a
child's, a TV's, a read-only one) could give itself one with set_pin and
then disarm with it on any keypad in the home.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from homeassistant.auth.const import GROUP_ID_READ_ONLY
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.smartservice_alarm.const import EVENT_ALARM, WS_SET_PIN
from custom_components.smartservice_alarm.pins import record_matches

from .conftest import ENTITY, alarm, give_pins, manager_of, set_pin

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}
OWN = "2468"


async def _read_only(hass: HomeAssistant) -> MockUser:
    group = await hass.auth.async_get_group(GROUP_ID_READ_ONLY)
    return MockUser(name="Telewizor", groups=[group]).add_to_hass(hass)


async def _client(hass: HomeAssistant, hass_ws_client, user: MockUser):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _ws_set_pin(client, user: MockUser, pin: str, **extra: Any) -> dict[str, Any]:
    await client.send_json_auto_id(
        {"type": WS_SET_PIN, "user_id": user.id, "pin": pin, **extra}
    )
    return await client.receive_json()


async def _caller(hass: HomeAssistant, users, kind: str) -> MockUser:
    return users.piotr if kind == "zwykle" else await _read_only(hass)


@pytest.mark.parametrize("kind", ["zwykle", "tylko_odczyt"])
async def test_no_first_pin_by_the_action(hass, users, loaded, kind) -> None:
    caller = await _caller(hass, users, kind)
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)

    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, caller, caller, OWN)
    assert err.value.translation_key == "first_pin_by_admin"

    await hass.async_block_till_done()
    manager = manager_of(loaded)
    assert not manager.has_pin(caller.id)
    # Nothing was guessed: no failed attempt, no lock, no logbook entry.
    assert manager.lockouts == {}
    assert found == []


@pytest.mark.parametrize("kind", ["zwykle", "tylko_odczyt"])
async def test_no_first_pin_by_websocket(hass, users, loaded, hass_ws_client, kind) -> None:
    caller = await _caller(hass, users, kind)
    client = await _client(hass, hass_ws_client, caller)

    answer = await _ws_set_pin(client, caller, OWN)
    assert answer["success"] is False
    assert answer["error"]["translation_key"] == "first_pin_by_admin"
    assert not manager_of(loaded).has_pin(caller.id)
    assert manager_of(loaded).lockouts == {}


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_a_self_made_pin_does_not_disarm(hass, users, loaded, hass_ws_client) -> None:
    """The attack: the TV gives itself a PIN, the keypad tablet uses it."""
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr, pins["piotr"])
    tv = await _read_only(hass)
    client = await _client(hass, hass_ws_client, tv)

    assert (await _ws_set_pin(client, tv, OWN))["success"] is False
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", users.tablet, OWN)
    assert err.value.translation_key == "wrong_pin"
    assert hass.states.get(ENTITY).state == "armed_away"


async def test_the_owner_still_changes_his_pin(hass, users, loaded, hass_ws_client) -> None:
    """A PIN from an administrator: its owner changes it, also read-only."""
    tv = await _read_only(hass)
    await set_pin(hass, users.admin, tv, "1357")
    await set_pin(hass, users.admin, users.piotr, "8642")

    client = await _client(hass, hass_ws_client, tv)
    answer = await _ws_set_pin(client, tv, OWN, current_pin="1357")
    assert answer["result"] == {"wynik": "ok"}
    await set_pin(hass, users.piotr, users.piotr, "3579", current_pin="8642")

    manager = manager_of(loaded)
    assert record_matches(manager.pins[tv.id], OWN)
    assert record_matches(manager.pins[users.piotr.id], "3579")


async def test_admin_still_sets_any_first_pin(hass, users, loaded) -> None:
    tv = await _read_only(hass)
    await set_pin(hass, users.admin, users.admin, "1357")
    await set_pin(hass, users.admin, tv, OWN)
    manager = manager_of(loaded)
    assert manager.has_pin(users.admin.id)
    assert manager.has_pin(tv.id)
