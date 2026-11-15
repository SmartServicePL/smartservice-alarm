"""1.5.0: PIN pod przymusem.

Drugi PIN domownika działa dokładnie jak jego PIN (ten sam stan, ten sam wpis
w dzienniku, ta sama odpowiedź), a integracja wysyła dodatkowo jedno zdarzenie
osobnego typu, którego dziennik nie pokazuje - bez PIN-u. Ustawia go
administrator; domownik zmienia tylko swój istniejący, podając swój PIN.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.smartservice_alarm import pins as pins_module
from custom_components.smartservice_alarm.const import (
    EVENT_ALARM,
    EVENT_CODE,
    WS_CHECK_PIN,
    WS_CLEAR_PIN,
    WS_DISARM,
    WS_SET_PIN,
)
from custom_components.smartservice_alarm.pins import record_matches

from .conftest import ENTITY, alarm, give_pins, make_entry, manager_of, service

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}
DURESS = "7314"


async def _client(hass: HomeAssistant, hass_ws_client, user: MockUser):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _send(client, kind: str, **fields: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": kind, **fields})
    return await client.receive_json()


async def _set_duress(
    hass: HomeAssistant, caller: MockUser, target: MockUser, pin: str, current: str | None = None
) -> None:
    data: dict[str, Any] = {"user_id": target.id, "pin": pin, "rodzaj": "przymus"}
    if current is not None:
        data["current_pin"] = current
    await service(hass, "set_pin", caller, data)


def _listen(hass: HomeAssistant, kind: str) -> list[Event]:
    found: list[Event] = []
    hass.bus.async_listen(kind, found.append)
    return found


def _without_time(events: list[Event]) -> list[dict[str, Any]]:
    return [dict(event.data) for event in events]


def _calls(events: list[Event]) -> list[Event]:
    """The code events of a duress PIN (the silent alarm)."""
    return [event for event in events if event.data["przymus"] is True]


CODE_KEYS = {"entity_id", "wlasciciel_id", "przymus", "czas"}


# -- ustawianie ----------------------------------------------------------------


async def test_the_administrator_sets_it_without_a_logbook_entry(hass, users, loaded) -> None:
    await give_pins(hass, users)
    found = _listen(hass, EVENT_ALARM)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    await hass.async_block_till_done()
    manager = manager_of(loaded)
    assert manager.has_duress(users.piotr.id)
    assert record_matches(manager.duress[users.piotr.id], DURESS)
    # His PIN stays; nothing in the logbook tells that a duress PIN exists.
    assert record_matches(manager.pins[users.piotr.id], "1357")
    assert found == []


async def test_only_for_somebody_with_a_pin(hass, users, loaded) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.admin, users.piotr, DURESS)
    assert err.value.translation_key == "duress_needs_pin"
    assert not manager_of(loaded).has_duress(users.piotr.id)


async def test_a_user_changes_only_his_existing_one(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    manager = manager_of(loaded)
    # The first one comes from an administrator - nothing guessed, nothing counted.
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.piotr, users.piotr, DURESS, pins["piotr"])
    assert err.value.translation_key == "first_pin_by_admin"
    assert manager.lockouts == {}
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    # His own, with his (normal) PIN.
    await _set_duress(hass, users.piotr, users.piotr, "3816", pins["piotr"])
    assert record_matches(manager.duress[users.piotr.id], "3816")
    # Not somebody else's.
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.piotr, users.adam, "5927", pins["piotr"])
    assert err.value.translation_key == "own_pin_only"


async def test_every_pin_of_both_kinds_is_different(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    manager = manager_of(loaded)
    # His own PIN: refused, not counted (he knows it).
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.piotr, users.piotr, pins["piotr"], pins["piotr"])
    assert err.value.translation_key == "pin_taken"
    assert manager.lockouts == {}
    # His PIN may not become his duress PIN either.
    with pytest.raises(ServiceValidationError) as err:
        await service(
            hass, "set_pin", users.piotr,
            {"user_id": users.piotr.id, "pin": DURESS, "current_pin": pins["piotr"]},
        )
    assert err.value.translation_key == "pin_taken"
    assert manager.lockouts == {}
    # Somebody else's PIN or duress PIN: counted, as with his PIN.
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.piotr, users.piotr, pins["adam"], pins["piotr"])
    assert err.value.translation_key == "pin_taken"
    assert manager.lockouts[users.piotr.id]["nieudane"] == 1
    await _set_duress(hass, users.admin, users.adam, "4071")
    with pytest.raises(ServiceValidationError) as err:
        await service(
            hass, "set_pin", users.piotr,
            {"user_id": users.piotr.id, "pin": "4071", "current_pin": pins["piotr"]},
        )
    assert manager.lockouts[users.piotr.id]["nieudane"] == 2
    # An administrator: refused, never counted.
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.admin, users.adam, pins["piotr"])
    assert err.value.translation_key == "pin_taken"
    assert users.admin.id not in manager.lockouts


async def test_his_duress_pin_as_the_current_one_changes_the_duress_pin(
    hass, users, loaded
) -> None:
    """W-1: „change PIN” with the duress PIN as the current one is accepted
    like his PIN; the silent alarm goes and the duress PIN gets the new one."""
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    manager = manager_of(loaded)
    # A real change first, for the same answer and logbook entries.
    normal_alarm = _listen(hass, EVENT_ALARM)
    normal_codes = _listen(hass, EVENT_CODE)
    change = {"user_id": users.piotr.id, "pin": "2749", "current_pin": pins["piotr"]}
    await service(hass, "set_pin", users.piotr, change)
    await hass.async_block_till_done()
    assert record_matches(manager.pins[users.piotr.id], "2749")
    forced_alarm = _listen(hass, EVENT_ALARM)
    forced_codes = _listen(hass, EVENT_CODE)
    forced = {"user_id": users.piotr.id, "pin": "5927", "current_pin": DURESS}
    await service(hass, "set_pin", users.piotr, forced)
    await hass.async_block_till_done()
    # Answered like a change; his PIN untouched, the duress PIN is the new one.
    assert record_matches(manager.pins[users.piotr.id], "2749")
    assert record_matches(manager.duress[users.piotr.id], "5927")
    assert manager.lockouts == {}
    actions = [e.data.get("akcja") for e in forced_alarm]
    assert actions == [e.data.get("akcja") for e in normal_alarm[: len(forced_alarm)]]
    first = normal_codes[: len(normal_codes) - len(forced_codes)]
    assert [e.data["przymus"] for e in first] == [False]
    assert [e.data["przymus"] for e in forced_codes] == [True]
    assert forced_codes[0].data["wlasciciel_id"] == users.piotr.id


async def test_setting_a_duress_pin_with_it_answers_as_without_one(hass, users, loaded) -> None:
    """N-1: „set the duress PIN” with the duress PIN as the current one answers
    like for somebody without a duress PIN - nothing changes or is counted,
    the silent alarm goes anyway."""
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    manager = manager_of(loaded)
    # Adam has no duress PIN: his own PIN as the current one.
    adam_alarm = _listen(hass, EVENT_ALARM)
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.adam, users.adam, "5927", pins["adam"])
    assert err.value.translation_key == "first_pin_by_admin"
    await hass.async_block_till_done()
    # Piotr's duress PIN as the current one: the same answer.
    alarm_found = _listen(hass, EVENT_ALARM)
    codes = _listen(hass, EVENT_CODE)
    with pytest.raises(ServiceValidationError) as err:
        await _set_duress(hass, users.piotr, users.piotr, "5927", DURESS)
    await hass.async_block_till_done()
    assert err.value.translation_key == "first_pin_by_admin"
    assert manager.lockouts == {}
    assert alarm_found == [] and adam_alarm == []
    # Nothing changed: the duress PIN still works, the new one does not.
    assert record_matches(manager.duress[users.piotr.id], DURESS)
    assert not record_matches(manager.duress[users.piotr.id], "5927")
    assert record_matches(manager.pins[users.piotr.id], pins["piotr"])
    # The silent alarm went.
    assert [(e.data["przymus"], e.data["wlasciciel_id"]) for e in codes] == [(True, users.piotr.id)]


async def test_a_member_changes_his_pins_at_most_3_times_an_hour(hass, users, loaded) -> None:
    """N-2: more own changes count as failed attempts (the same locks)."""
    pins = await give_pins(hass, users)
    manager = manager_of(loaded)
    current = pins["piotr"]
    for new in ("2749", "3816", "4927"):
        change = {"user_id": users.piotr.id, "pin": new, "current_pin": current}
        await service(hass, "set_pin", users.piotr, change)
        current = new
    assert manager.lockouts == {}
    with pytest.raises(ServiceValidationError) as err:
        change = {"user_id": users.piotr.id, "pin": "5038", "current_pin": current}
        await service(hass, "set_pin", users.piotr, change)
    assert err.value.translation_key == "too_many_pin_changes"
    assert manager.lockouts[users.piotr.id]["nieudane"] == 1
    assert record_matches(manager.pins[users.piotr.id], current)
    # An administrator is not limited.
    for new in ("6149", "7250", "8361", "9472"):
        await service(hass, "set_pin", users.admin, {"user_id": users.adam.id, "pin": new})


async def test_nothing_tells_a_duress_pin_without_the_pin(hass, users, loaded) -> None:
    """W-2: a user's current PIN is checked (and counted) first - the answer
    without it is the same whether he has a duress PIN or not."""
    await give_pins(hass, users)
    manager = manager_of(loaded)
    answers = []
    for setup in (False, True):
        if setup:
            manager.book.unlock(users.piotr.id)
            await _set_duress(hass, users.admin, users.piotr, DURESS)
        with pytest.raises(ServiceValidationError) as err:
            await _set_duress(hass, users.piotr, users.piotr, "5927", "9999")
        answers.append(err.value.translation_key)
        assert manager.lockouts[users.piotr.id]["nieudane"] >= 1
    assert answers == ["wrong_current_pin", "wrong_current_pin"]


# -- działanie -----------------------------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_it_disarms_exactly_like_his_pin(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)

    # With his PIN.
    await alarm(hass, "alarm_arm_away", users.adam, pins["adam"])
    normal = _listen(hass, EVENT_ALARM)
    normal_codes = _listen(hass, EVENT_CODE)
    await alarm(hass, "alarm_disarm", users.tablet, pins["piotr"])
    await hass.async_block_till_done()
    normal_state = hass.states.get(ENTITY)
    normal_codes = list(normal_codes)

    # With his duress PIN.
    await alarm(hass, "alarm_arm_away", users.adam, pins["adam"])
    codes = _listen(hass, EVENT_CODE)
    alarm_found = _listen(hass, EVENT_ALARM)
    await alarm(hass, "alarm_disarm", users.tablet, DURESS)
    await hass.async_block_till_done()
    current = hass.states.get(ENTITY)

    assert current.state == normal_state.state == "disarmed"
    for key in ("changed_by", "zmiana_przez"):
        assert current.attributes.get(key) == normal_state.attributes.get(key)
    assert current.attributes["changed_by"] == "Piotr"
    assert _without_time(alarm_found) == _without_time(normal[: len(alarm_found)])
    assert [event.data.get("akcja") for event in alarm_found] == ["rozbrojenie"]
    assert all("przymus" not in str(event.data) for event in alarm_found)
    # One code event each time, the same keys; only „przymus” differs.
    assert len(codes) == len(normal_codes[:1]) == 1
    assert set(codes[0].data) == set(normal_codes[0].data) == CODE_KEYS
    assert normal_codes[0].data["przymus"] is False
    data = codes[0].data
    assert data["przymus"] is True
    assert (data["entity_id"], data["wlasciciel_id"]) == (ENTITY, users.piotr.id)
    assert normal_codes[0].data["wlasciciel_id"] == users.piotr.id
    assert DURESS not in str(data) and pins["piotr"] not in str(data)
    assert codes[0].context.user_id == users.tablet.id


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_it_arms_like_his_pin_and_calls(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    codes = _listen(hass, EVENT_CODE)
    await alarm(hass, "alarm_arm_home", users.piotr, DURESS)
    await hass.async_block_till_done()
    current = hass.states.get(ENTITY)
    assert current.state == "armed_home"
    assert current.attributes["changed_by"] == "Piotr"
    assert [event.data["wlasciciel_id"] for event in _calls(codes)] == [users.piotr.id]


async def test_the_entry_to_security_and_the_websocket(hass, users, loaded, hass_ws_client) -> None:
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    codes = _listen(hass, EVENT_CODE)
    client = await _client(hass, hass_ws_client, users.tablet)

    normal = await _send(client, WS_CHECK_PIN, pin=pins["piotr"])
    forced = await _send(client, WS_CHECK_PIN, pin=DURESS)
    assert normal["result"] == forced["result"]
    assert forced["result"] == {**forced["result"], "wynik": "poprawny", "osoba": "Piotr"}
    assert (await _send(client, WS_DISARM, code=DURESS))["result"] == {"wynik": "ok"}
    await hass.async_block_till_done()
    assert [event.data["przymus"] for event in codes] == [False, True, True]


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_a_wrong_code_is_still_wrong(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    await alarm(hass, "alarm_arm_away", users.adam, "8642")
    codes = _listen(hass, EVENT_CODE)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", users.tablet, "7315")
    await hass.async_block_till_done()
    assert err.value.translation_key == "wrong_pin"
    # A wrong code fires the code event too (the same logbook entry), no owner.
    assert [(e.data["przymus"], e.data["wlasciciel_id"]) for e in codes] == [(False, None)]
    assert hass.states.get(ENTITY).state == "armed_away"


async def test_the_work_does_not_tell_which_kind(hass, users, loaded, scrypt_calls) -> None:
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    manager = manager_of(loaded)
    counts = []
    for code in (pins["adam"], DURESS, "5038"):
        before = scrypt_calls.calls
        await manager.async_check_entry(users.tablet.id, code, None)
        counts.append(scrypt_calls.calls - before)
    # Every stored PIN of both kinds is hashed each time: 4 PINs + 1 duress PIN.
    assert counts == [5, 5, 5]


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_a_lock_does_not_swallow_the_silent_alarm(
    hass, users, loaded, hass_ws_client, scrypt_calls
) -> None:
    """D-1: during a lock the code is not accepted, but a right duress PIN still
    calls for help; every locked attempt fires the event and hashes the same."""
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    await alarm(hass, "alarm_arm_away", users.adam, pins["adam"])
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.piotr, "4826")
    manager = manager_of(loaded)
    assert manager.locked_until(users.piotr.id) is not None
    codes = _listen(hass, EVENT_CODE)
    counts, keys = [], []
    for code in (pins["piotr"], DURESS, "5038"):
        before = scrypt_calls.calls
        with pytest.raises(ServiceValidationError) as err:
            await alarm(hass, "alarm_disarm", users.piotr, code)
        counts.append(scrypt_calls.calls - before)
        keys.append(err.value.translation_key)
    await hass.async_block_till_done()
    assert keys == ["locked_out"] * 3
    assert hass.states.get(ENTITY).state == "armed_away"
    # Only the duress PINs are hashed during a lock - the same work every time.
    assert counts == [1, 1, 1]
    assert [e.data["przymus"] for e in codes] == [False, True, False]
    assert _calls(codes)[0].data["wlasciciel_id"] == users.piotr.id
    # The entry to Bezpieczeństwo the same way.
    client = await _client(hass, hass_ws_client, users.piotr)
    codes.clear()
    answer = await _send(client, WS_CHECK_PIN, pin=DURESS)
    await hass.async_block_till_done()
    assert answer["result"]["wynik"] == "zablokowany"
    assert [e.data["przymus"] for e in codes] == [True]


# -- usuwanie, stan, pamięć -------------------------------------------------------


async def test_clearing(hass, users, loaded, hass_ws_client) -> None:
    await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    await _set_duress(hass, users.admin, users.adam, "4071")
    manager = manager_of(loaded)
    found = _listen(hass, EVENT_ALARM)
    client = await _client(hass, hass_ws_client, users.admin)

    # Only the duress PIN - his PIN stays, no logbook entry.
    answer = await _send(client, WS_CLEAR_PIN, user_id=users.adam.id, rodzaj="przymus")
    assert answer["result"] == {"wynik": "ok", "usuniety": True}
    assert not manager.has_duress(users.adam.id) and manager.has_pin(users.adam.id)
    await hass.async_block_till_done()
    assert found == []
    # His PIN - the duress PIN goes with it.
    await service(hass, "clear_pin", users.admin, {"user_id": users.piotr.id})
    assert not manager.has_pin(users.piotr.id) and not manager.has_duress(users.piotr.id)
    await hass.async_block_till_done()
    assert [event.data["akcja"] for event in found] == ["pin_usuniety"]


async def test_status_tells_the_administrator(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    status = await service(hass, "status", users.admin, response=True)
    assert status[users.piotr.id]["pin_przymus"] is True
    assert status[users.adam.id]["pin_przymus"] is False


async def test_kept_after_a_restart_and_dropped_with_the_user(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    manager = manager_of(loaded)
    assert record_matches(manager.duress[users.piotr.id], DURESS)
    assert manager.remove_unknown_users({users.admin.id, users.adam.id, users.tablet.id})
    assert not manager.has_duress(users.piotr.id)


# 6 digits: a chance hit inside the base64 of a salt or a hash is practically
# impossible, so the PIN is searched for as a token of its own everywhere.
WS_DURESS = "619427"
# Home Assistant's own websocket debug log (README: off by default).
WS_API_LOG = "homeassistant.components.websocket_api"


def _alone(pin: str) -> re.Pattern[str]:
    """The PIN as a token: no digit or letter on either side."""
    return re.compile(rf"(?<![0-9A-Za-z]){pin}(?![0-9A-Za-z])")


async def _stored(hass_storage: dict[str, Any], entry: Any) -> dict[str, Any]:
    """The integration's Store as written (saved now, not after the delay)."""
    await manager_of(entry).async_save()
    return hass_storage[f"smartservice_alarm.{entry.entry_id}"]["data"]


async def test_websocket_kind_checked_without_logging_the_pin(
    hass, users, loaded, hass_ws_client, caplog, hass_storage
) -> None:
    await give_pins(hass, users)
    client = await _client(hass, hass_ws_client, users.admin)
    caplog.set_level(logging.DEBUG)
    answer = await _send(client, WS_SET_PIN, user_id=users.piotr.id, pin=WS_DURESS, rodzaj="inny")
    assert answer["success"] is False
    assert answer["error"]["translation_key"] == "unknown_pin_kind"
    assert not manager_of(loaded).has_duress(users.piotr.id)
    # The right kind by websocket.
    answer = await _send(
        client, WS_SET_PIN, user_id=users.piotr.id, pin=WS_DURESS, rodzaj="przymus"
    )
    assert answer["result"] == {"wynik": "ok"}
    assert manager_of(loaded).has_duress(users.piotr.id)
    await hass.async_block_till_done()
    stored = json.dumps(await _stored(hass_storage, loaded))
    # Every logger at DEBUG. The one exception is Home Assistant's own debug
    # log of the websocket API: it writes every received message, this PIN
    # too (README, "off by default; keep it off") - the integration cannot
    # change it. Anywhere else in the log, and in the Store as written: never.
    own = [r for r in caplog.records if not r.name.startswith(WS_API_LOG)]
    texts = ["\n".join(r.getMessage() for r in own), stored]
    for text in texts:
        assert not _alone(WS_DURESS).search(text)
        assert f'"{WS_DURESS}"' not in text and f"'{WS_DURESS}'" not in text
    # ... and that exception is only the received message itself.
    for record in caplog.records:
        if _alone(WS_DURESS).search(record.getMessage()):
            assert record.name.startswith(WS_API_LOG), record.name
            assert "Received {" in record.getMessage(), record.getMessage()[:80]


async def test_the_store_keeps_only_a_salt_and_a_scrypt_hash(
    hass, users, loaded, hass_storage
) -> None:
    pins = await give_pins(hass, users)
    await _set_duress(hass, users.admin, users.piotr, WS_DURESS)
    data = await _stored(hass_storage, loaded)
    records = {
        **{f"pin:{k}": v for k, v in data["piny"].items()},
        **{f"przymus:{k}": v for k, v in data["przymus"].items()},
    }
    assert f"przymus:{users.piotr.id}" in records
    for name, record in records.items():
        # Only the salt, the hash, scrypt's parameters and the change's time.
        assert set(record) == {"salt", "hash", "n", "r", "p", "zmieniono"}, name
        assert len(base64.b64decode(record["salt"], validate=True)) == pins_module.SALT_BYTES
        assert len(base64.b64decode(record["hash"], validate=True)) == pins_module.SCRYPT_DKLEN
        # The parameters in force (the fixture lowers N and r for speed; the
        # production values are pinned by test_pins.test_production_parameters).
        assert (record["n"], record["r"], record["p"]) == (
            pins_module.SCRYPT_N,
            pins_module.SCRYPT_R,
            pins_module.SCRYPT_P,
        ), name
    # Each record is the scrypt of its own PIN (and of no other).
    assert record_matches(records[f"przymus:{users.piotr.id}"], WS_DURESS)
    assert not record_matches(records[f"przymus:{users.piotr.id}"], pins["piotr"])
    assert record_matches(records[f"pin:{users.piotr.id}"], pins["piotr"])
    # No PIN in a plain form anywhere in the Store: as it is, reversed, in
    # base64, hex, or a fast unsalted hash.
    text = json.dumps(data)
    for pin in (*pins.values(), WS_DURESS):
        raw = pin.encode()
        forms = {
            pin,
            pin[::-1],
            base64.b64encode(raw).decode(),
            raw.hex(),
            hashlib.md5(raw).hexdigest(),
            hashlib.sha1(raw).hexdigest(),
            hashlib.sha256(raw).hexdigest(),
            base64.b64encode(hashlib.sha256(raw).digest()).decode(),
        }
        for form in forms:
            assert not _alone(re.escape(form)).search(text), (pin, form)


async def test_a_pins_only_entry_calls_too(hass, users, hass_ws_client) -> None:
    entry = make_entry(hass)
    hass.config_entries.async_update_entry(entry, data={"name": "Piny", "rodzaj": "piny"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await service(hass, "set_pin", users.admin, {"user_id": users.piotr.id, "pin": "1357"})
    await _set_duress(hass, users.admin, users.piotr, DURESS)
    codes = _listen(hass, EVENT_CODE)
    client = await _client(hass, hass_ws_client, users.piotr)
    answer = await _send(client, WS_CHECK_PIN, pin=DURESS)
    assert answer["result"]["wynik"] == "poprawny"
    await hass.async_block_till_done()
    assert [event.data["wlasciciel_id"] for event in _calls(codes)] == [users.piotr.id]
    assert codes[0].data["entity_id"] is None


def test_the_code_event_is_not_the_logbook_one() -> None:
    assert EVENT_CODE != EVENT_ALARM
    assert "napad" not in EVENT_CODE
