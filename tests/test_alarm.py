"""Centrala: uzbrajanie, rozbrajanie, wyzwolenie, G1, G3, G4 i restart."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import Event
from homeassistant.exceptions import ServiceValidationError

from custom_components.smartservice_alarm.const import DOMAIN, EVENT_ALARM

from .conftest import ENTITY, alarm, ctx, give_pins, manager_of

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}


def state(hass):
    return hass.states.get(ENTITY)


async def tick(hass, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def trigger(hass, user=None, czujnik: str | None = None) -> None:
    data = {"entity_id": ENTITY}
    if czujnik is not None:
        data["czujnik"] = czujnik
    await hass.services.async_call(DOMAIN, "trigger", data, blocking=True, context=ctx(user))


def captured(hass) -> list[Event]:
    found: list[Event] = []
    hass.bus.async_listen(EVENT_ALARM, found.append)
    return found


async def refused(hass, service, user, code=None) -> str:
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, service, user, code)
    return err.value.translation_key


# -- disarming with each user's PIN ------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_disarm_with_each_pin_sets_changed_by(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    events = captured(hass)
    names = {"admin": "Zbigniew", "anna": "Anna", "marek": "Marek", "tablet": "Tablet salon"}
    for key, pin in pins.items():
        await alarm(hass, "alarm_arm_away", users.anna)
        assert state(hass).state == "armed_away"
        await alarm(hass, "alarm_disarm", users.tablet, pin)
        current = state(hass)
        assert current.state == "disarmed"
        assert current.attributes["changed_by"] == names[key]
        assert current.attributes["zmiana_przez"] == "uzytkownik"
    await hass.async_block_till_done()
    disarms = [e.data for e in events if e.data["akcja"] == "rozbrojenie"]
    assert disarms[1]["wlasciciel"] == "Anna"
    assert disarms[1]["konto"] == "Tablet salon"
    assert disarms[1]["tryb"] == "armed_away"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_wrong_pin_and_missing_pin(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    assert await refused(hass, "alarm_disarm", users.anna, "4826") == "wrong_pin"
    assert await refused(hass, "alarm_disarm", users.anna) == "pin_required"
    assert await refused(hass, "alarm_disarm", users.anna, "") == "pin_required"
    assert state(hass).state == "armed_away"


async def test_wrong_pin_message_is_translated(hass, users, loaded) -> None:
    await give_pins(hass, users)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", users.anna, "4826")
    # The backend message is always English without the final period; the
    # Polish text comes from translations/pl.json via the translation key.
    assert str(err.value) == "Wrong PIN"
    assert err.value.translation_domain == DOMAIN


async def test_entity_default_code_is_ignored(hass, users, loaded) -> None:
    """Kod domyślny z ustawień encji nie zastępuje PIN-u."""
    from homeassistant.helpers import entity_registry as er

    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    er.async_get(hass).async_update_entity_options(
        ENTITY, "alarm_control_panel", {"default_code": pins["anna"]}
    )
    await hass.async_block_till_done()
    assert await refused(hass, "alarm_disarm", users.anna) == "pin_required"


# -- arming, modes, G3 ----------------------------------------------------------


@pytest.mark.parametrize("entry_options", [{"arm_home": False, "arm_night": False}])
async def test_disabled_mode(hass, users, loaded) -> None:
    assert await refused(hass, "alarm_arm_home", users.anna) == "mode_disabled"
    assert await refused(hass, "alarm_arm_night", None) == "mode_disabled"
    await alarm(hass, "alarm_arm_away", users.anna)
    assert state(hass).state == "arming"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_g3_optional_code(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_home", users.tablet, pins["marek"])
    assert state(hass).attributes["changed_by"] == "Marek"
    await alarm(hass, "alarm_disarm", users.tablet, pins["marek"])

    assert await refused(hass, "alarm_arm_home", users.tablet, "4826") == "wrong_pin"
    assert manager_of(loaded).lockouts[users.tablet.id]["nieudane"] == 1
    assert state(hass).state == "disarmed"

    await alarm(hass, "alarm_arm_home", users.tablet)
    current = state(hass)
    assert current.state == "armed_home"
    assert current.attributes["changed_by"] == "Tablet salon"
    assert current.attributes["uzbrojenie_przez_automat"] is False


@pytest.mark.parametrize("entry_options", [{**NO_DELAYS, "code_arm_required": True}])
async def test_code_required_for_arming(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_away", None)
    # Raised by the alarm panel base class before the integration is called.
    assert err.value.translation_key == "code_arm_required"
    assert await refused(hass, "alarm_arm_away", users.anna, "4826") == "wrong_pin"
    await alarm(hass, "alarm_arm_away", users.anna, pins["anna"])
    assert state(hass).state == "armed_away"


async def test_exit_delay(hass, users, loaded, freezer) -> None:
    await alarm(hass, "alarm_arm_away", users.anna)
    current = state(hass)
    assert current.state == "arming"
    assert current.attributes["tryb"] == "armed_away"
    assert current.attributes["koniec_odliczania"] is not None
    await tick(hass, freezer, 59)
    assert state(hass).state == "arming"
    await tick(hass, freezer, 2)
    assert state(hass).state == "armed_away"
    assert state(hass).attributes["koniec_odliczania"] is None


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_arming_by_automation_attributes(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", None)
    current = state(hass)
    assert current.state == "armed_night"
    assert current.attributes["changed_by"] == "Automatyzacja"
    assert current.attributes["zmiana_przez"] == "automatyzacja"
    assert current.attributes["uzbrojenie_przez_automat"] is True


# -- G4 sensors -----------------------------------------------------------------

SENSORS = {
    **NO_DELAYS,
    "sensors": ["binary_sensor.okno_salon", "binary_sensor.drzwi_taras"],
}


def sensors(hass, okno: str, drzwi: str | None) -> None:
    hass.states.async_set("binary_sensor.okno_salon", okno, {"friendly_name": "okno salon"})
    if drzwi is not None:
        hass.states.async_set(
            "binary_sensor.drzwi_taras", drzwi, {"friendly_name": "drzwi taras"}
        )


@pytest.mark.parametrize("entry_options", [SENSORS])
@pytest.mark.parametrize("who", ["anna", None])
async def test_g4_open_sensors_refuse(hass, users, loaded, who) -> None:
    user = getattr(users, who) if who else None
    sensors(hass, "on", "on")
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_away", user)
    assert err.value.translation_key == "sensors_open"
    assert err.value.translation_placeholders == {"czujniki": "okno salon, drzwi taras"}
    assert state(hass).state == "disarmed"


@pytest.mark.parametrize("entry_options", [SENSORS])
@pytest.mark.parametrize("who", ["anna", None])
async def test_g4_unavailable_sensors_refuse(hass, users, loaded, who) -> None:
    user = getattr(users, who) if who else None
    sensors(hass, "off", "unavailable")
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_night", user)
    assert err.value.translation_key == "sensors_unavailable"
    assert err.value.translation_placeholders == {"czujniki": "drzwi taras"}

    hass.states.async_remove("binary_sensor.drzwi_taras")
    sensors(hass, "unknown", None)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_night", user)
    assert err.value.translation_placeholders == {
        "czujniki": "okno salon, binary_sensor.drzwi_taras"
    }
    assert state(hass).state == "disarmed"


@pytest.mark.parametrize("entry_options", [SENSORS])
async def test_g4_closed_sensors_arm(hass, users, loaded) -> None:
    sensors(hass, "off", "off")
    await alarm(hass, "alarm_arm_away", None)
    assert state(hass).state == "armed_away"


# -- trigger --------------------------------------------------------------------


async def test_trigger_pending_triggered_back_to_armed(hass, users, loaded, freezer) -> None:
    events = captured(hass)
    await alarm(hass, "alarm_arm_away", users.anna)
    # During the exit delay a trigger is ignored.
    await trigger(hass, czujnik="drzwi ogrodowe")
    assert state(hass).state == "arming"
    await tick(hass, freezer, 61)
    assert state(hass).state == "armed_away"

    await trigger(hass, czujnik="drzwi ogrodowe")
    current = state(hass)
    assert current.state == "pending"
    assert current.attributes["czujnik_wyzwalajacy"] == "drzwi ogrodowe"
    assert current.attributes["zmiana_przez"] == "wyzwolenie"
    await tick(hass, freezer, 29)
    assert state(hass).state == "pending"
    await tick(hass, freezer, 2)
    assert state(hass).state == "triggered"
    await tick(hass, freezer, 30 * 60 - 1)
    assert state(hass).state == "triggered"
    await tick(hass, freezer, 2)
    current = state(hass)
    assert current.state == "armed_away"
    assert current.attributes["czujnik_wyzwalajacy"] == "drzwi ogrodowe"
    triggers = [e.data for e in events if e.data["akcja"] == "wyzwolenie"]
    assert triggers == [
        {
            "entity_id": ENTITY,
            "akcja": "wyzwolenie",
            "tryb": "armed_away",
            "czujnik": "drzwi ogrodowe",
        }
    ]


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_standard_alarm_trigger(hass, users, loaded) -> None:
    await alarm(hass, "alarm_trigger", None)
    assert state(hass).state == "disarmed"
    await alarm(hass, "alarm_arm_home", None)
    await alarm(hass, "alarm_trigger", None)
    assert state(hass).state == "triggered"
    assert state(hass).attributes["czujnik_wyzwalajacy"] is None
    assert await refused(hass, "alarm_arm_away", users.anna) == "disarm_first"


async def test_disarm_during_pending(hass, users, loaded, freezer) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    await tick(hass, freezer, 61)
    await trigger(hass, czujnik="ruch hol")
    assert state(hass).state == "pending"
    await alarm(hass, "alarm_disarm", users.anna, pins["anna"])
    assert state(hass).state == "disarmed"
    assert state(hass).attributes["czujnik_wyzwalajacy"] is None
    await tick(hass, freezer, 3600)
    assert state(hass).state == "disarmed"


# -- G1 ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_g1_automation_disarms_own_night_arming(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", None)
    await alarm(hass, "alarm_disarm", None)
    current = state(hass)
    assert current.state == "disarmed"
    assert current.attributes["changed_by"] == "Automatyzacja"
    assert current.attributes["zmiana_przez"] == "automatyzacja"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_g1_not_after_user_arming(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", users.anna)
    assert await refused(hass, "alarm_disarm", None) == "pin_required"
    assert state(hass).state == "armed_night"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_g1_only_night_mode(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_away", None)
    assert await refused(hass, "alarm_disarm", None) == "pin_required"
    await alarm(hass, "alarm_arm_home", None)
    assert await refused(hass, "alarm_disarm", None) == "pin_required"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_g1_user_call_needs_pin(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", None)
    assert await refused(hass, "alarm_disarm", users.anna) == "pin_required"


@pytest.mark.parametrize("entry_options", [{"entry_delay": 30}])
async def test_g1_not_after_pending_or_triggered(hass, users, loaded, freezer) -> None:
    await alarm(hass, "alarm_arm_night", None)
    await tick(hass, freezer, 61)
    assert state(hass).state == "armed_night"
    await trigger(hass, czujnik="okno sypialnia")
    assert state(hass).state == "pending"
    assert await refused(hass, "alarm_disarm", None) == "pin_required"
    await tick(hass, freezer, 31)
    assert state(hass).state == "triggered"
    assert await refused(hass, "alarm_disarm", None) == "pin_required"
    await tick(hass, freezer, 30 * 60 + 1)
    assert state(hass).state == "armed_night"
    assert state(hass).attributes["uzbrojenie_przez_automat"] is True
    assert await refused(hass, "alarm_disarm", None) == "pin_required"


async def test_g1_not_during_exit_delay(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", None)
    assert state(hass).state == "arming"
    assert await refused(hass, "alarm_disarm", None) == "pin_required"


# -- restart ------------------------------------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_state_survives_restart(hass, users, loaded) -> None:
    await alarm(hass, "alarm_arm_night", None)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    current = state(hass)
    assert current.state == "armed_night"
    assert current.attributes["uzbrojenie_przez_automat"] is True
    assert current.attributes["changed_by"] == "Automatyzacja"
    # G1 still applies after the restart.
    await alarm(hass, "alarm_disarm", None)
    assert state(hass).state == "disarmed"


async def test_countdowns_resume_after_restart(hass, users, loaded, freezer) -> None:
    await alarm(hass, "alarm_arm_away", users.anna)
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await tick(hass, freezer, 30)
    assert await hass.config_entries.async_setup(loaded.entry_id)
    await hass.async_block_till_done()
    assert state(hass).state == "arming"
    await tick(hass, freezer, 31)
    assert state(hass).state == "armed_away"

    await trigger(hass, czujnik="drzwi")
    assert await hass.config_entries.async_unload(loaded.entry_id)
    # Down for the whole entry delay and part of the alarm.
    await tick(hass, freezer, 30 + 60)
    assert await hass.config_entries.async_setup(loaded.entry_id)
    await hass.async_block_till_done()
    assert state(hass).state == "triggered"
    await tick(hass, freezer, 29 * 60 + 1)
    assert state(hass).state == "armed_away"
