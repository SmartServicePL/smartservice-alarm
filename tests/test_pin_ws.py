"""1.4.0: PIN tylko przez polecenia websocket (uzbrajanie, rozbrajanie, PIN-y).

Te same metody encji, uprawnienia, liczniki i blokady co usługi; PIN nie
trafia do zdarzeń call_service ani do logów. Baza recordera:
test_check_pin_recorder.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from homeassistant.auth.const import GROUP_ID_READ_ONLY
from homeassistant.const import EVENT_CALL_SERVICE, MATCH_ALL
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.smartservice_alarm.const import (
    EVENT_ALARM,
    WS_ARM,
    WS_CHECK_PIN,
    WS_CLEAR_PIN,
    WS_DISARM,
    WS_SET_PIN,
)

from .conftest import ENTITY, alarm, give_pins, make_entry, manager_of

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}
WRONG = "4826"


async def _client(hass: HomeAssistant, hass_ws_client, user: MockUser):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _send(client, kind: str, **fields: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": kind, **fields})
    return await client.receive_json()


def _error(answer: dict[str, Any]) -> str:
    assert answer["success"] is False, answer
    return answer["error"]["translation_key"] or answer["error"]["code"]


def _alone(pin: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z]){pin}(?![0-9A-Za-z])")


def _events(hass: HomeAssistant) -> list[Event]:
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    return found


# -- uzbrajanie i rozbrajanie ---------------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_arm_and_disarm_like_the_services(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    found = _events(hass)
    client = await _client(hass, hass_ws_client, users.tablet)

    answer = await _send(client, WS_ARM, tryb="away", code=pins["adam"])
    assert answer == {**answer, "success": True, "result": {"wynik": "ok"}}
    current = hass.states.get(ENTITY)
    assert current.state == "armed_away"
    assert current.attributes["changed_by"] == "Adam"
    assert current.attributes["zmiana_przez"] == "uzytkownik"

    assert (await _send(client, WS_DISARM, code=pins["piotr"]))["result"] == {"wynik": "ok"}
    assert hass.states.get(ENTITY).state == "disarmed"
    assert hass.states.get(ENTITY).attributes["changed_by"] == "Piotr"

    for mode, state in (("home", "armed_home"), ("night", "armed_night")):
        await _send(client, WS_ARM, tryb=mode, code=pins["piotr"])
        assert hass.states.get(ENTITY).state == state
        await _send(client, WS_DISARM, code=pins["piotr"])
    await hass.async_block_till_done()
    actions = [e.data["akcja"] for e in found]
    assert actions[:2] == ["uzbrojenie", "rozbrojenie"]
    assert found[0].data["wlasciciel"] == "Adam"
    assert found[0].data["konto"] == "Tablet salon"
    assert found[0].context.user_id == users.tablet.id


async def test_exit_delay_and_mode_rules_are_the_panels(hass, users, hass_ws_client) -> None:
    entry = make_entry(hass, arm_night=False)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)

    assert _error(await _send(client, WS_ARM, tryb="night", code=pins["piotr"])) == (
        "mode_disabled"
    )
    await _send(client, WS_ARM, tryb="away", code=pins["piotr"])
    assert hass.states.get(ENTITY).state == "arming"
    # An unknown mode is refused by the schema (the mode is no secret).
    answer = await _send(client, WS_ARM, tryb="vacation", code=pins["piotr"])
    assert answer["success"] is False


@pytest.mark.parametrize("entry_options", [{**NO_DELAYS, "code_arm_required": True}])
async def test_code_required_wrong_and_missing(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)

    missing = await _send(client, WS_ARM, tryb="away")
    assert _error(missing) == "code_arm_required"
    assert missing["error"]["translation_domain"] == "alarm_control_panel"
    wrong = await _send(client, WS_ARM, tryb="away", code=WRONG)
    assert _error(wrong) == "wrong_pin"
    assert wrong["error"]["translation_domain"] == "smartservice_alarm"
    assert _error(await _send(client, WS_DISARM)) == "pin_required"
    await _send(client, WS_ARM, tryb="away", code=int(pins["piotr"]))
    assert hass.states.get(ENTITY).state == "armed_away"
    # A value that is not a PIN is just no PIN.
    assert _error(await _send(client, WS_DISARM, code=["x"])) == "pin_required"
    assert hass.states.get(ENTITY).state == "armed_away"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_one_counter_for_every_way(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    await _send(client, WS_ARM, tryb="away", code=WRONG)
    await _send(client, WS_DISARM, code=WRONG)
    await _send(client, WS_CHECK_PIN, pin=WRONG)
    with pytest.raises(ServiceValidationError):
        await alarm(hass, "alarm_arm_away", users.piotr, WRONG)
    locked = await _send(client, WS_ARM, tryb="away", code=WRONG)
    assert _error(locked) == "locked_out"
    assert set(locked["error"]["translation_placeholders"]) == {"godzina"}
    assert _error(await _send(client, WS_ARM, tryb="away", code=pins["piotr"])) == (
        "locked_out"
    )
    assert hass.states.get(ENTITY).state == "disarmed"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_control_permission_is_checked(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    read_only = MockUser(
        name="Gość", groups=[await hass.auth.async_get_group(GROUP_ID_READ_ONLY)]
    ).add_to_hass(hass)
    client = await _client(hass, hass_ws_client, read_only)
    answer = await _send(client, WS_ARM, tryb="away", code=pins["piotr"])
    assert answer["error"]["code"] == "unauthorized"
    assert hass.states.get(ENTITY).state == "disarmed"
    # Refused before the PIN is checked: nothing counted.
    assert read_only.id not in manager_of(loaded).lockouts


async def test_unknown_and_ambiguous_alarm(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    for kind, fields in (
        (WS_ARM, {"tryb": "away", "code": pins["piotr"]}),
        (WS_DISARM, {"code": pins["piotr"]}),
        (WS_SET_PIN, {"user_id": users.piotr.id, "pin": "3579", "current_pin": pins["piotr"]}),
    ):
        answer = await _send(client, kind, entity_id="alarm_control_panel.inny", **fields)
        assert _error(answer) == "unknown_alarm"
        assert _error(await _send(client, kind, entity_id=5, **fields)) == "unknown_alarm"
    second = make_entry(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    answer = await _send(client, WS_DISARM, code=pins["piotr"])
    assert _error(answer) == "choose_alarm"


# -- PIN-y ----------------------------------------------------------------------


async def test_set_and_clear_pin_like_the_services(hass, users, loaded, hass_ws_client) -> None:
    found = _events(hass)
    admin = await _client(hass, hass_ws_client, users.admin)
    piotr = await _client(hass, hass_ws_client, users.piotr)

    assert (await _send(admin, WS_SET_PIN, user_id=users.piotr.id, pin="1357"))[
        "result"
    ] == {"wynik": "ok"}
    # A user changes his own PIN with the current one ...
    assert _error(await _send(piotr, WS_SET_PIN, user_id=users.piotr.id, pin="3579")) == (
        "current_pin_required"
    )
    changed = await _send(
        piotr, WS_SET_PIN, user_id=users.piotr.id, pin="3579", current_pin="1357"
    )
    assert changed["result"] == {"wynik": "ok"}
    # ... and never somebody else's.
    assert _error(await _send(piotr, WS_SET_PIN, user_id=users.adam.id, pin="8642")) == (
        "own_pin_only"
    )
    assert _error(await _send(admin, WS_SET_PIN, user_id="nikt", pin="8642")) == (
        "unknown_user"
    )
    assert _error(await _send(admin, WS_SET_PIN, user_id=users.adam.id, pin="1234")) == (
        "pin_trivial"
    )
    assert _error(await _send(admin, WS_SET_PIN, user_id=["x"], pin="8642")) == "unknown_user"

    assert _error(await _send(piotr, WS_CLEAR_PIN, user_id=users.piotr.id)) == (
        "admin_required"
    )
    cleared = await _send(admin, WS_CLEAR_PIN, user_id=users.piotr.id)
    assert cleared["result"] == {"wynik": "ok", "usuniety": True}
    again = await _send(admin, WS_CLEAR_PIN, user_id=users.piotr.id)
    assert again["result"] == {"wynik": "ok", "usuniety": False}

    await hass.async_block_till_done()
    assert [e.data["akcja"] for e in found] == [
        "pin_ustawiony",
        "pin_ustawiony",
        "pin_usuniety",
    ]
    assert not manager_of(loaded).has_pin(users.piotr.id)


async def test_collision_and_wrong_current_pin_count(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    for _ in range(2):
        answer = await _send(
            client, WS_SET_PIN, user_id=users.piotr.id, pin=pins["adam"], current_pin=pins["piotr"]
        )
        assert _error(answer) == "pin_taken"
    for _ in range(2):
        answer = await _send(
            client, WS_SET_PIN, user_id=users.piotr.id, pin="3579", current_pin=WRONG
        )
        assert _error(answer) == "wrong_current_pin"
    assert (await _send(client, WS_CHECK_PIN, pin=WRONG))["result"]["wynik"] == "zablokowany"


# -- ani zdarzeń call_service, ani PIN-u w logach ---------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_no_pin_in_events_attributes_or_logs(
    hass, users, loaded, hass_ws_client, caplog, hass_storage
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="custom_components.smartservice_alarm")
    seen: list[Event] = []
    hass.bus.async_listen(MATCH_ALL, seen.append)
    admin = await _client(hass, hass_ws_client, users.admin)
    piotr = await _client(hass, hass_ws_client, users.piotr)

    await _send(admin, WS_SET_PIN, user_id=users.piotr.id, pin="1357")
    await _send(piotr, WS_SET_PIN, user_id=users.piotr.id, pin="3579", current_pin="1357")
    await _send(piotr, WS_ARM, tryb="away", code="3579")
    await _send(piotr, WS_DISARM, code=WRONG)
    await _send(piotr, WS_DISARM, code="3579")
    await _send(piotr, WS_ARM, tryb="vacation", code="3579")
    await _send(admin, WS_CLEAR_PIN, user_id=users.piotr.id)
    await hass.async_block_till_done()

    assert not [e for e in seen if e.event_type == EVENT_CALL_SERVICE]
    text = json.dumps(
        {
            "events": [e.as_dict() for e in seen],
            "attributes": dict(hass.states.get(ENTITY).attributes),
            "storage": hass_storage,
        },
        default=str,
    )
    for pin in ("1357", "3579", WRONG):
        assert not _alone(pin).search(text), pin
        assert not _alone(pin).search(caplog.text), pin
