"""Z25 (one sensor at most 3 alarms in one arming) and Z21 (the break while
the alarm guarded is told after the start)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState

from custom_components.smartservice_alarm.events import describe

from .conftest import ENTITY, alarm, give_pins, manager_of
from .test_alarm import captured, state, tick, trigger

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}
ALARM_S = 10 * 60


def kinds(events, action: str) -> list[dict]:
    return [dict(event.data) for event in events if event.data["akcja"] == action]


async def one_alarm(hass, freezer, czujnik: str) -> None:
    await trigger(hass, czujnik=czujnik)
    assert state(hass).state == "triggered"
    await tick(hass, freezer, ALARM_S + 1)
    assert state(hass).state == "armed_away"


# -- Z25 ------------------------------------------------------------------------


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z25_a_sensor_bypassed_after_three_alarms_until_disarming(
    hass, users, loaded, freezer
) -> None:
    pins = await give_pins(hass, users)
    found = captured(hass)
    await alarm(hass, "alarm_arm_away", users.piotr)
    for _ in range(3):
        await one_alarm(hass, freezer, "okno salon")
    assert state(hass).attributes["czujniki_pominiete"] == []

    # The fourth: no alarm, told once.
    await trigger(hass, czujnik="okno salon")
    await hass.async_block_till_done()
    assert state(hass).state == "armed_away"
    assert state(hass).attributes["czujniki_pominiete"] == ["okno salon"]
    await trigger(hass, czujnik="okno salon")
    await hass.async_block_till_done()
    assert state(hass).state == "armed_away"
    told = kinds(found, "czujka_pominieta")
    assert told == [
        {
            "entity_id": ENTITY,
            "akcja": "czujka_pominieta",
            "tryb": "armed_away",
            "czujnik": "okno salon",
            "wyzwolenia": 3,
        }
    ]
    assert len(kinds(found, "wyzwolenie")) == 3

    # Another sensor still triggers.
    await trigger(hass, czujnik="drzwi taras")
    assert state(hass).state == "triggered"
    assert state(hass).attributes["czujnik_wyzwalajacy"] == "drzwi taras"

    # Disarming forgets the count: the next arming triggers again.
    await alarm(hass, "alarm_disarm", users.piotr, pins["piotr"])
    assert state(hass).attributes["czujniki_pominiete"] == []
    await alarm(hass, "alarm_arm_away", users.piotr)
    await trigger(hass, czujnik="okno salon")
    assert state(hass).state == "triggered"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z25_triggers_without_a_sensor_name_are_not_counted(
    hass, users, loaded, freezer
) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    for _ in range(4):
        await alarm(hass, "alarm_trigger", None)
        assert state(hass).state == "triggered"
        await tick(hass, freezer, ALARM_S + 1)


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z25_ignored_triggers_are_not_counted(hass, users, loaded, freezer) -> None:
    """A trigger during the alarm (ignored) is not one of the three."""
    await alarm(hass, "alarm_arm_away", users.piotr)
    await trigger(hass, czujnik="okno salon")
    for _ in range(5):
        await trigger(hass, czujnik="okno salon")
    await tick(hass, freezer, ALARM_S + 1)
    await one_alarm(hass, freezer, "okno salon")
    await one_alarm(hass, freezer, "okno salon")
    await trigger(hass, czujnik="okno salon")
    assert state(hass).attributes["czujniki_pominiete"] == ["okno salon"]


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z25_the_count_survives_a_restart(hass, users, loaded, freezer) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    for _ in range(3):
        await one_alarm(hass, freezer, "okno salon")
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    await trigger(hass, czujnik="okno salon")
    await hass.async_block_till_done()
    assert state(hass).state == "armed_away"
    assert state(hass).attributes["czujniki_pominiete"] == ["okno salon"]


def test_z25_logbook_text() -> None:
    data = {"akcja": "czujka_pominieta", "czujnik": "okno salon", "wyzwolenia": 3}
    assert describe(data, "pl") == (
        "Czujka pominięta do rozbrojenia: okno salon (3 alarmy z rzędu)"
    )
    assert describe(data, "en") == (
        "Sensor bypassed until disarming: okno salon (3 alarms in a row)"
    )


# -- Z21 ------------------------------------------------------------------------


async def restart(hass, entry, freezer, seconds: float) -> None:
    """Home Assistant down for ``seconds`` and started again."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(seconds=seconds))
    hass.set_state(CoreState.not_running)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z21_the_break_is_told_after_the_start(hass, users, loaded, freezer) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    found = captured(hass)
    await restart(hass, loaded, freezer, 7 * 60 - 20)
    assert state(hass).state == "armed_away"
    assert kinds(found, "powrot_po_przerwie") == [
        {
            "entity_id": ENTITY,
            "akcja": "powrot_po_przerwie",
            "tryb": "armed_away",
            "stan": "armed_away",
            "stan_przed": "armed_away",
            "przerwa_min": 7,
        }
    ]


async def test_z21_the_countdowns_caught_up_during_the_break(
    hass, users, loaded, freezer
) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    await tick(hass, freezer, 61)
    await trigger(hass, czujnik="drzwi")
    assert state(hass).state == "pending"
    found = captured(hass)
    await restart(hass, loaded, freezer, 60)
    told = kinds(found, "powrot_po_przerwie")
    assert len(told) == 1
    assert told[0]["stan_przed"] == "pending"
    assert told[0]["stan"] == "triggered"


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z21_the_moment_is_written_while_it_guards(
    hass, users, loaded, freezer
) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    before = manager_of(loaded).state["zywy"]
    await tick(hass, freezer, 5 * 60)
    later = manager_of(loaded).state["zywy"]
    assert later > before
    found = captured(hass)
    # A stop writes it too (the same writer listens to the stop): a start
    # right after tells a break of 1 minute.
    assert hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0) >= 1
    panel = hass.data["alarm_control_panel"].get_entity(ENTITY)
    freezer.tick(timedelta(seconds=40))
    await panel._async_alive(None)
    await restart(hass, loaded, freezer, 30)
    assert kinds(found, "powrot_po_przerwie")[0]["przerwa_min"] == 1


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z21_nothing_while_disarmed_or_on_a_reload(
    hass, users, loaded, freezer
) -> None:
    found = captured(hass)
    await restart(hass, loaded, freezer, 600)
    await alarm(hass, "alarm_arm_away", users.piotr)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    assert kinds(found, "powrot_po_przerwie") == []


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_z21_a_break_not_known_is_told_without_minutes(
    hass, users, loaded, freezer
) -> None:
    await alarm(hass, "alarm_arm_away", users.piotr)
    manager = manager_of(loaded)
    manager.state.pop("zywy")
    await manager.async_save()
    found = captured(hass)
    # The unload writes nothing new (the panel saves only on a change).
    assert await hass.config_entries.async_unload(loaded.entry_id)
    manager.state.pop("zywy", None)
    await manager.async_save()
    freezer.tick(timedelta(minutes=3))
    hass.set_state(CoreState.not_running)
    assert await hass.config_entries.async_setup(loaded.entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    told = kinds(found, "powrot_po_przerwie")
    assert len(told) == 1
    assert "przerwa_min" not in told[0]


def test_z21_logbook_text() -> None:
    assert describe({"akcja": "powrot_po_przerwie", "przerwa_min": 7}, "pl") == (
        "Alarm wrócił po 7 min przerwy"
    )
    assert describe({"akcja": "powrot_po_przerwie"}, "pl") == "Alarm wrócił po przerwie"
    assert describe({"akcja": "powrot_po_przerwie", "przerwa_min": 7}, "en") == (
        "Alarm back after a 7 min break"
    )
