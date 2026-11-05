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
        await lock(hass, users.piotr)
        assert locked_seconds(loaded, users.piotr.id) == pytest.approx(seconds)
        freezer.tick(timedelta(seconds=seconds + 1))
        async_fire_time_changed(hass)


async def test_lockout_message_has_local_time(hass, users, loaded, freezer) -> None:
    freezer.move_to("2026-10-17 16:04:30+00:00")
    await give_pins(hass, users)
    for _ in range(4):
        await wrong(hass, users.piotr)
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_disarm", users.piotr, WRONG)
    until = dt_util.as_local(dt_util.parse_datetime("2026-10-17 16:06:00+00:00"))
    assert err.value.translation_key == "locked_out"
    assert err.value.translation_placeholders == {"godzina": until.strftime("%H:%M")}


async def test_locked_attempts_skip_scrypt(hass, users, loaded, scrypt_calls) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr)
    await lock(hass, users.piotr)
    calls = scrypt_calls.calls
    assert await wrong(hass, users.piotr) == "locked_out"
    # Even the correct PIN is refused during the lockout, without hashing.
    assert await wrong(hass, users.piotr, pins["piotr"]) == "locked_out"
    with pytest.raises(ServiceValidationError) as err:
        await alarm(hass, "alarm_arm_home", users.piotr, pins["piotr"])
    assert err.value.translation_key == "locked_out"
    assert scrypt_calls.calls == calls


async def test_lockout_per_account(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr)
    await lock(hass, users.tablet)
    # Another account still works, also with the tablet owner's PIN.
    await alarm(hass, "alarm_disarm", users.adam, pins["tablet"])
    assert hass.states.get("alarm_control_panel.dom").state == "disarmed"
    assert manager_of(loaded).locked_until(users.adam.id) is None
    assert manager_of(loaded).locked_until(users.tablet.id) is not None


async def test_calls_without_user_share_one_bucket(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, None)
    assert manager_of(loaded).locked_until("_bez_konta") is not None
    assert manager_of(loaded).locked_until(users.piotr.id) is None


async def test_correct_code_does_not_reset_streak(hass, users, loaded) -> None:
    """Decyzja GŁÓWNEGO: 4 złe, dobry kod, 1 zły = blokada."""
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr)
    for _ in range(4):
        await wrong(hass, users.piotr)
    await alarm(hass, "alarm_disarm", users.piotr, pins["piotr"])
    await alarm(hass, "alarm_arm_away", users.piotr)
    assert await wrong(hass, users.piotr) == "locked_out"


async def test_streak_expires_after_15_min(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    for _ in range(4):
        await wrong(hass, users.piotr)
    freezer.tick(timedelta(minutes=14, seconds=59))
    assert await wrong(hass, users.piotr) == "locked_out"
    await service(hass, "unlock", users.admin, {"user_id": users.piotr.id})
    for _ in range(4):
        await wrong(hass, users.piotr)
    freezer.tick(timedelta(minutes=15))
    assert await wrong(hass, users.piotr) == "wrong_pin"


async def test_level_drops_one_step_per_day(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    for seconds in (60, 120, 240):
        await lock(hass, users.piotr)
        assert locked_seconds(loaded, users.piotr.id) == pytest.approx(seconds, abs=2)
        freezer.tick(timedelta(seconds=seconds + 1))
        async_fire_time_changed(hass)
    # Poziom 3: po jednej dobie bez błędów następna blokada jak przy poziomie 3
    # (240 s zamiast 480 s), po dwóch dobach jak przy poziomie 2 (120 s).
    freezer.tick(timedelta(hours=24))
    await lock(hass, users.piotr)
    assert locked_seconds(loaded, users.piotr.id) == pytest.approx(240, abs=2)
    freezer.tick(timedelta(hours=48))
    await lock(hass, users.piotr)
    assert locked_seconds(loaded, users.piotr.id) == pytest.approx(120, abs=2)


async def test_pin_change_keeps_lockout(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, users.piotr)
    await set_pin(hass, users.admin, users.piotr, "3579")
    assert manager_of(loaded).locked_until(users.piotr.id) is not None
    assert await wrong(hass, users.piotr, "3579") == "locked_out"


async def test_admin_unlock(hass, users, loaded) -> None:
    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr)
    await lock(hass, users.piotr)
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "unlock", users.adam, {"user_id": users.piotr.id})
    assert err.value.translation_key == "admin_required"
    await service(hass, "unlock", users.admin, {"user_id": users.piotr.id})
    await alarm(hass, "alarm_disarm", users.piotr, pins["piotr"])
    assert hass.states.get("alarm_control_panel.dom").state == "disarmed"

    await lock(hass, None)
    await service(hass, "unlock", users.admin, {"user_id": "_bez_konta"})
    assert manager_of(loaded).locked_until("_bez_konta") is None


async def test_constant_work(hass, users, loaded, scrypt_calls) -> None:
    """Każde sprawdzenie liczy skrót dla każdego zapisanego użytkownika."""
    pins = await give_pins(hass, users)
    for code in (pins["piotr"], WRONG, pins["admin"], "97531"):
        before = scrypt_calls.calls
        with suppress(ServiceValidationError):
            await alarm(hass, "alarm_disarm", users.adam, code)
        assert scrypt_calls.calls - before == 4


async def test_lockout_survives_restart(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await lock(hass, users.piotr)
    for _ in range(2):
        await wrong(hass, users.adam)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    manager = manager_of(loaded)
    assert manager.locked_until(users.piotr.id) is not None
    assert manager.lockouts[users.adam.id]["nieudane"] == 2
    assert manager.lockouts[users.piotr.id]["poziom"] == 1
    assert await wrong(hass, users.piotr) == "locked_out"


async def test_z29_one_counter_for_the_whole_panel(hass, users, loaded) -> None:
    """Z29 (30.10): 15 wrong codes from several accounts within 15 minutes lock
    every account but the administrators; an administrator's unlock ends it."""

    pins = await give_pins(hass, users)
    await alarm(hass, "alarm_arm_away", users.piotr)
    await lock(hass, users.piotr)
    await lock(hass, users.adam)
    for _ in range(4):
        assert await wrong(hass, users.tablet) == "wrong_pin"
    # The 15th wrong code, from yet another caller: the whole panel locked.
    assert await wrong(hass, None) == "wrong_pin"
    assert manager_of(loaded).locked_until("_cala_centrala") is not None
    # The tablet's own streak is at 4 - its right PIN is refused all the same.
    assert await wrong(hass, users.tablet, pins["tablet"]) == "locked_out"
    # An administrator still disarms (and the attempt does not count).
    await alarm(hass, "alarm_disarm", users.admin, pins["admin"])
    assert hass.states.get("alarm_control_panel.dom").state == "disarmed"
    await service(hass, "unlock", users.admin, {"user_id": users.tablet.id})
    assert manager_of(loaded).locked_until("_cala_centrala") is None
    await alarm(hass, "alarm_arm_away", users.tablet, pins["tablet"])


async def test_z29_one_account_alone_keeps_its_own_lock(hass, users, loaded, freezer) -> None:
    await give_pins(hass, users)
    for _ in range(3):
        await lock(hass, users.piotr)
        freezer.tick(timedelta(minutes=16))
    assert manager_of(loaded).locked_until("_cala_centrala") is None
