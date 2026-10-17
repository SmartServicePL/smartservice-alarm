"""status, uprawnienia, dziennik, diagnostyka i brak PIN-ów w logach."""

from __future__ import annotations

import json
import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import Event
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.smartservice_alarm import logbook as logbook_module
from custom_components.smartservice_alarm.const import DOMAIN, EVENT_ALARM
from custom_components.smartservice_alarm.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.smartservice_alarm.events import describe

from .conftest import ENTITY, alarm, give_pins, make_entry, manager_of, service, set_pin

WRONG = "4826"


async def test_status_for_admin_without_secrets(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await service(hass, "clear_pin", users.admin, {"user_id": users.marek.id})
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.anna, WRONG)

    response = await service(hass, "status", users.admin, response=True)
    assert response[users.admin.id] == {"pin": True, "zablokowany_do": None}
    assert response[users.marek.id] == {"pin": False, "zablokowany_do": None}
    assert response[users.anna.id]["pin"] is True
    until = dt_util.parse_datetime(response[users.anna.id]["zablokowany_do"])
    assert until > dt_util.utcnow()
    text = json.dumps(response)
    for pin in pins.values():
        assert pin not in text
    for record in manager_of(loaded).pins.values():
        assert record["salt"] not in text
        assert record["hash"] not in text


async def test_status_admin_only(hass, users, loaded) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "status", users.anna, response=True)
    assert err.value.translation_key == "admin_required"
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "status", None, response=True)
    assert err.value.translation_key == "user_required"
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "unlock", None, {"user_id": users.anna.id})
    assert err.value.translation_key == "user_required"


async def test_status_lists_no_account_bucket_when_locked(hass, users, loaded) -> None:
    await give_pins(hass, users)
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_disarm", None, WRONG)
    response = await service(hass, "status", users.admin, response=True)
    assert response["_bez_konta"]["zablokowany_do"] is not None


async def test_two_alarms_need_entity_id(hass, users, loaded) -> None:
    other = MockConfigEntry(domain=DOMAIN, title="Garaż", data={"name": "Garaż"})
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.admin, users.anna, "2468")
    assert err.value.translation_key == "choose_alarm"
    await service(
        hass,
        "set_pin",
        users.admin,
        {"user_id": users.anna.id, "pin": "2468", "entity_id": "alarm_control_panel.garaz"},
    )
    assert other.runtime_data.has_pin(users.anna.id)
    assert not manager_of(loaded).has_pin(users.anna.id)
    with pytest.raises(ServiceValidationError) as err:
        await service(
            hass, "status", users.admin, {"entity_id": "alarm_control_panel.nie_ma"}, response=True
        )
    assert err.value.translation_key == "unknown_alarm"


async def test_unknown_users_removed_at_startup(hass, users, hass_storage) -> None:
    entry = make_entry(hass)
    record = {"salt": "AAAA", "hash": "BBBB", "n": 16, "r": 1, "p": 1, "zmieniono": None}
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "piny": {"usuniety": record, users.anna.id: record},
            "blokady": {
                "usuniety": {"nieudane": 2, "poziom": 0, "do": None},
                "_bez_konta": {"nieudane": 1, "poziom": 0, "do": None},
            },
            "stan": {},
        },
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = manager_of(entry)
    assert set(manager.pins) == {users.anna.id}
    assert set(manager.lockouts) == {"_bez_konta"}


async def test_diagnostics_redact_salt_and_hash(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    data = await async_get_config_entry_diagnostics(hass, loaded)
    text = json.dumps(data)
    for record in manager_of(loaded).pins.values():
        assert record["salt"] not in text
        assert record["hash"] not in text
    for pin in pins.values():
        assert pin not in text
    assert data["piny"][users.anna.id]["salt"] == "**REDACTED**"
    assert data["piny"][users.anna.id]["n"] == 16
    # The manager's own data is untouched.
    assert manager_of(loaded).pins[users.anna.id]["salt"] != "**REDACTED**"


async def test_events_and_logbook_text(hass, users, loaded) -> None:
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.marek, WRONG)
    await alarm(hass, "alarm_disarm", users.tablet, pins["anna"])
    await hass.async_block_till_done()

    texts = [describe(dict(e.data), "pl") for e in found]
    assert "PIN ustawiony: Anna (z konta: Zbigniew)" in texts
    assert "Uzbrojenie (poza domem): Anna" in texts
    assert "Błędny PIN z konta Marek (3/5)" in texts
    assert any(t.startswith("Blokada konta Marek do ") for t in texts)
    assert "Rozbrojenie: Anna (z konta: Tablet salon)" in texts
    assert describe(dict(found[-1].data), "en") == "Disarmed: Anna (from account: Tablet salon)"
    assert describe({"akcja": "wyzwolenie", "czujnik": "drzwi ogrodowe"}, "pl") == (
        "Alarm: drzwi ogrodowe"
    )
    for event in found:
        text = json.dumps(event.data)
        for pin in pins.values():
            assert pin not in text

    described = {}

    def collect(domain, event_type, describer) -> None:
        described[(domain, event_type)] = describer

    logbook_module.async_describe_events(hass, collect)
    describer = described[(DOMAIN, EVENT_ALARM)]
    hass.config.language = "pl"
    entry = describer(found[-1])
    assert entry["name"] == "Dom"
    assert entry["message"] == "Rozbrojenie: Anna (z konta: Tablet salon)"
    assert entry["entity_id"] == ENTITY


async def test_no_pin_in_logs(hass, users, loaded, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.smartservice_alarm")
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna, pins["anna"])
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.marek, WRONG)
    with pytest.raises(ServiceValidationError):
        await set_pin(hass, users.anna, users.anna, "3579", current_pin=WRONG)
    await set_pin(hass, users.anna, users.anna, "3579", current_pin=pins["anna"])
    await alarm(hass, "alarm_disarm", users.anna, "3579")
    for pin in (*pins.values(), WRONG, "3579"):
        assert pin not in caplog.text
