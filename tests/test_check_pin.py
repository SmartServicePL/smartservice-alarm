"""1.3.0: sprawdzenie PIN-u przy wejściu do „Bezpieczeństwo” (polecenie websocket).

Polecenie websocket, nie usługa: dane każdego wywołania usługi trafiają do
zdarzenia call_service, a recorder zapisuje je do bazy. Tu PIN nie trafia
nigdzie: ani do zdarzeń, ani do bazy, ani do logów, ani do odpowiedzi.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from homeassistant.const import EVENT_CALL_SERVICE, MATCH_ALL
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.smartservice_alarm.const import EVENT_ALARM, WS_CHECK_PIN
from custom_components.smartservice_alarm.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.smartservice_alarm.events import describe

from .conftest import ENTITY, alarm, give_pins, make_entry, manager_of

WRONG = "4826"


async def _client(hass: HomeAssistant, hass_ws_client, user: MockUser):
    """Websocket client signed in as the given user."""
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _check(client, pin: Any, **extra: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": WS_CHECK_PIN, "pin": pin, **extra})
    return await client.receive_json()


def _alarm_events(hass: HomeAssistant) -> list[Event]:
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    return found


def _alone(pin: str) -> re.Pattern[str]:
    """A PIN on its own: four digits can occur by chance inside a timestamp
    or a hexadecimal id."""
    return re.compile(rf"(?<![0-9A-Za-z]){pin}(?![0-9A-Za-z])")


async def test_correct_pin_gives_the_person(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    before = hass.states.get(ENTITY)
    found = _alarm_events(hass)
    client = await _client(hass, hass_ws_client, users.piotr)

    answer = await _check(client, pins["piotr"])

    assert answer["success"] is True
    assert answer["result"] == {
        "wynik": "poprawny",
        "user_id": users.piotr.id,
        "osoba": "Piotr",
    }
    await hass.async_block_till_done()
    after = hass.states.get(ENTITY)
    assert (after.state, dict(after.attributes)) == (before.state, dict(before.attributes))
    assert [e.data["akcja"] for e in found] == ["wejscie_bezpieczenstwo"]
    assert describe(dict(found[0].data), "pl") == "Piotr: wejście do Bezpieczeństwa"
    assert describe(dict(found[0].data), "en") == "Piotr: entered Security"


async def test_shared_tablet_gives_the_owner_of_the_pin(
    hass, users, loaded, hass_ws_client
) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.tablet)
    answer = await _check(client, pins["adam"])
    assert answer["result"] == {"wynik": "poprawny", "user_id": users.adam.id, "osoba": "Adam"}


async def test_wrong_pins_count_down_and_lock(
    hass, users, loaded, hass_ws_client, scrypt_calls
) -> None:
    pins = await give_pins(hass, users)
    found = _alarm_events(hass)
    client = await _client(hass, hass_ws_client, users.piotr)

    left = [(await _check(client, WRONG))["result"] for _ in range(4)]
    assert left == [{"wynik": "niepoprawny", "pozostalo": n} for n in (4, 3, 2, 1)]
    fifth = (await _check(client, WRONG))["result"]
    assert fifth["wynik"] == "zablokowany"
    assert dt_util.parse_datetime(fifth["do"]) > dt_util.utcnow()

    # Locked: even the right PIN is refused and not hashed at all.
    calls = scrypt_calls.calls
    locked = (await _check(client, pins["piotr"]))["result"]
    assert locked == {"wynik": "zablokowany", "do": fifth["do"]}
    assert scrypt_calls.calls == calls

    await hass.async_block_till_done()
    actions = [e.data["akcja"] for e in found]
    assert actions == ["wejscie_bezpieczenstwo_nieudane"] * 5 + ["blokada"]
    failed = dict(found[0].data)
    assert describe(failed, "pl") == "Nieudana próba wejścia do Bezpieczeństwa"
    assert describe(failed, "en") == "Failed attempt to enter Security"
    # The lock is told as with arming.
    assert describe(dict(found[-1].data), "pl").startswith("Blokada konta Piotr do ")
    assert hass.states.get(ENTITY).state == "disarmed"


async def test_counter_is_shared_with_arming(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    for _ in range(3):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_arm_away", users.piotr, WRONG)
    assert (await _check(client, WRONG))["result"] == {"wynik": "niepoprawny", "pozostalo": 1}
    assert (await _check(client, WRONG))["result"]["wynik"] == "zablokowany"
    # ... and the lock stops arming with a PIN too.
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_away", users.piotr, pins["piotr"])
    assert err.value.translation_key == "locked_out"


async def test_entry_failures_lock_arming(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.adam)
    for _ in range(4):
        await _check(client, WRONG)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_away", users.adam, WRONG)
    assert err.value.translation_key == "locked_out"
    answer = (await _check(client, pins["adam"]))["result"]
    assert answer["wynik"] == "zablokowany"


async def test_a_correct_pin_does_not_clear_the_streak(
    hass, users, loaded, hass_ws_client
) -> None:
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    for _ in range(3):
        await _check(client, WRONG)
    assert (await _check(client, pins["piotr"]))["result"]["wynik"] == "poprawny"
    assert (await _check(client, WRONG))["result"] == {"wynik": "niepoprawny", "pozostalo": 1}


async def test_whole_panel_lock_spares_only_administrators(
    hass, users, loaded, hass_ws_client
) -> None:
    pins = await give_pins(hass, users)
    clients = {
        name: await _client(hass, hass_ws_client, getattr(users, name))
        for name in ("piotr", "adam", "tablet", "admin")
    }
    # Z29: 15 wrong PINs from at least two accounts lock the whole panel.
    # A locked account stops counting, so 4 + 4 + 4 + 3 over four accounts:
    # none of them reaches its own limit of 5.
    for name, tries in (("piotr", 4), ("adam", 4), ("tablet", 4), ("admin", 3)):
        for _ in range(tries):
            await _check(clients[name], WRONG)
    locked = (await _check(clients["tablet"], pins["tablet"]))["result"]
    assert locked["wynik"] == "zablokowany"
    admin = (await _check(clients["admin"], pins["admin"]))["result"]
    assert admin == {"wynik": "poprawny", "user_id": users.admin.id, "osoba": "Jan"}


async def test_odd_values_count_as_a_wrong_pin_and_are_never_logged(
    hass, users, loaded, hass_ws_client, caplog
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="custom_components.smartservice_alarm")
    pins = await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)

    # A number is the PIN as text; anything else is just a wrong PIN.
    assert (await _check(client, int(pins["piotr"])))["result"]["wynik"] == "poprawny"
    odd = (await _check(client, ["7391"]))["result"]
    assert odd == {"wynik": "niepoprawny", "pozostalo": 4}
    assert (await _check(client, None))["result"] == {"wynik": "niepoprawny", "pozostalo": 3}
    assert not _alone("7391").search(caplog.text)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


async def test_unknown_or_ambiguous_alarm(hass, users, loaded, hass_ws_client) -> None:
    await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.piotr)
    answer = await _check(client, WRONG, entity_id="alarm_control_panel.inny")
    assert answer["success"] is False
    assert answer["error"]["code"] == "unknown_alarm"
    answer = await _check(client, WRONG, entity_id=["x"])
    assert answer["error"]["code"] == "unknown_alarm"

    second = make_entry(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    answer = await _check(client, WRONG)
    assert answer["error"]["code"] == "choose_alarm"
    # None of these counted as a wrong PIN.
    answer = await _check(client, WRONG, entity_id=ENTITY)
    assert answer["result"] == {"wynik": "niepoprawny", "pozostalo": 4}


async def test_no_pin_in_events_attributes_logs_storage_or_diagnostics(
    hass, users, loaded, hass_ws_client, caplog, hass_storage
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="custom_components.smartservice_alarm")
    pins = await give_pins(hass, users)
    seen: list[Event] = []
    hass.bus.async_listen(MATCH_ALL, seen.append)
    client = await _client(hass, hass_ws_client, users.piotr)

    await _check(client, pins["piotr"])
    for _ in range(5):
        await _check(client, WRONG)
    await hass.async_block_till_done()

    assert not [e for e in seen if e.event_type == EVENT_CALL_SERVICE]
    text = json.dumps(
        {
            "events": [e.as_dict() for e in seen],
            "attributes": dict(hass.states.get(ENTITY).attributes),
            "storage": hass_storage,
            "diagnostics": await async_get_config_entry_diagnostics(hass, loaded),
        },
        default=str,
    )
    for pin in (pins["piotr"], WRONG):
        assert not _alone(pin).search(text)
        assert not _alone(pin).search(caplog.text)
    for record in manager_of(loaded).pins.values():
        assert record["hash"] not in json.dumps([e.as_dict() for e in seen], default=str)
