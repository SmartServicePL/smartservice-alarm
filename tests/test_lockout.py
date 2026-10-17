"""Zgadywanie PIN-u: blokada per konto, podwajanie, stała praca, restart."""

from __future__ import annotations

from contextlib import suppress
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .conftest import alarm, give_pins, manager_of, service, set_pin

WRONG = "4826"


async def wrong(hass, user, code: str = WRONG) -> str:
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", user, code)
    return err.value.translation_key


async def lock(hass, user) -> None:
    for _ in range(4):
        assert await wrong(hass, user) == "wrong_pin"
    assert await wrong(hass, user) == "locked_out"


def locked_seconds(entry, bucket) -> float:
    until = manager_of(entry).locked_until(bucket)
    assert until is not None
    return (until - dt_util.utcnow()).total_seconds()


async def test_five_wrong_lock_for_60_s_then_doubling(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    expected = [60, 120, 240, 480, 900, 900]
    for seconds in expected:
        await lock(hass, users.anna)
        assert locked_seconds(loaded, users.anna.id) == pytest.approx(seconds)
        freezer.tick(timedelta(seconds=seconds + 1))
        async_fire_time_changed(hass)


async def test_lockout_message_has_local_time(hass, users, loaded, freezer) -> None:
    freezer.move_to("2026-10-17 16:04:30+00:00")
    await give_pins(hass, users)
    for _ in range(4):
        await wrong(hass, users.anna)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", users.anna, WRONG)
    until = dt_util.as_local(dt_util.parse_datetime("2026-10-17 16:06:00+00:00"))
    assert err.value.translation_key == "locked_out"
    assert err.value.translation_placeholders == {"godzina": until.strftime("%H:%M")}


async def test_locked_attempts_skip_scrypt(hass, users, loaded, scrypt_calls) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    await lock(hass, users.anna)
    calls = scrypt_calls.calls
    assert await wrong(hass, users.anna) == "locked_out"
    # Even the correct PIN is refused during the lockout, without hashing.
    assert await wrong(hass, users.anna, pins["anna"]) == "locked_out"
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_home", users.anna, pins["anna"])
    assert err.value.translation_key == "locked_out"
    assert scrypt_calls.calls == calls


async def test_lockout_per_account(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    await lock(hass, users.tablet)
    # Another account still works, also with the tablet owner's PIN.
    await alarm(hass, "alarm_disarm", users.marek, pins["tablet"])
    assert hass.states.get("alarm_control_panel.dom").state == "disarmed"
    assert manager_of(loaded).locked_until(users.marek.id) is None
    assert manager_of(loaded).locked_until(users.tablet.id) is not None


async def test_calls_without_user_share_one_bucket(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, None)
    assert manager_of(loaded).locked_until("_bez_konta") is not None
    assert manager_of(loaded).locked_until(users.anna.id) is None


async def test_correct_code_does_not_reset_streak(hass, users, loaded) -> None:
    """Decyzja GŁÓWNEGO: 4 złe, dobry kod, 1 zły = blokada."""
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    for _ in range(4):
        await wrong(hass, users.anna)
    await alarm(hass, "alarm_disarm", users.anna, pins["anna"])
    await alarm(hass, "alarm_arm_away", users.anna)
    assert await wrong(hass, users.anna) == "locked_out"


async def test_streak_expires_after_15_min(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    for _ in range(4):
        await wrong(hass, users.anna)
    freezer.tick(timedelta(minutes=14, seconds=59))
    assert await wrong(hass, users.anna) == "locked_out"
    await service(hass, "unlock", users.admin, {"user_id": users.anna.id})
    for _ in range(4):
        await wrong(hass, users.anna)
    freezer.tick(timedelta(minutes=15))
    assert await wrong(hass, users.anna) == "wrong_pin"


async def test_level_drops_one_step_per_day(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    for seconds in (60, 120, 240):
        await lock(hass, users.anna)
        assert locked_seconds(loaded, users.anna.id) == pytest.approx(seconds, abs=2)
        freezer.tick(timedelta(seconds=seconds + 1))
        async_fire_time_changed(hass)
    # Poziom 3: po jednej dobie bez błędów następna blokada jak przy poziomie 3
    # (240 s zamiast 480 s), po dwóch dobach jak przy poziomie 2 (120 s).
    freezer.tick(timedelta(hours=24))
    await lock(hass, users.anna)
    assert locked_seconds(loaded, users.anna.id) == pytest.approx(240, abs=2)
    freezer.tick(timedelta(hours=48))
    await lock(hass, users.anna)
    assert locked_seconds(loaded, users.anna.id) == pytest.approx(120, abs=2)


async def test_pin_change_keeps_lockout(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, users.anna)
    await set_pin(hass, users.admin, users.anna, "3579")
    assert manager_of(loaded).locked_until(users.anna.id) is not None
    assert await wrong(hass, users.anna, "3579") == "locked_out"


async def test_admin_unlock(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.anna)
    await lock(hass, users.anna)
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "unlock", users.marek, {"user_id": users.anna.id})
    assert err.value.translation_key == "admin_required"
    await service(hass, "unlock", users.admin, {"user_id": users.anna.id})
    await alarm(hass, "alarm_disarm", users.anna, pins["anna"])
    assert hass.states.get("alarm_control_panel.dom").state == "disarmed"

    await lock(hass, None)
    await service(hass, "unlock", users.admin, {"user_id": "_bez_konta"})
    assert manager_of(loaded).locked_until("_bez_konta") is None


async def test_constant_work(hass, users, loaded, scrypt_calls) -> None:
    """Każde sprawdzenie liczy skrót dla każdego zapisanego użytkownika."""
    pins = await give_pins(hass, users)
    for code in (pins["anna"], WRONG, pins["admin"], "97531"):
        before = scrypt_calls.calls
        with suppress(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.marek, code)
        assert scrypt_calls.calls - before == 4


async def test_lockout_survives_restart(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, users.anna)
    for _ in range(2):
        await wrong(hass, users.marek)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    manager = manager_of(loaded)
    assert manager.locked_until(users.anna.id) is not None
    assert manager.lockouts[users.marek.id]["nieudane"] == 2
    assert manager.lockouts[users.anna.id]["poziom"] == 1
    assert await wrong(hass, users.anna) == "locked_out"
