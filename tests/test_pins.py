"""PIN-y: reguły, skróty, unikalność i uprawnienia set_pin (z G2)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.smartservice_alarm import pins as pins_module
from custom_components.smartservice_alarm.pins import (
    lock_seconds,
    new_record,
    pin_problem,
    record_matches,
)

from .conftest import give_pins, manager_of, service, set_pin


@pytest.mark.parametrize(
    ("pin", "problem"),
    [
        ("123", "pin_format"),
        ("123456789", "pin_format"),
        ("12a4", "pin_format"),
        ("".join(chr(0xFF10 + d) for d in (1, 2, 3, 5)), "pin_format"),  # full-width
        (" 2580", "pin_format"),
        ("0000", "pin_trivial"),
        ("77777777", "pin_trivial"),
        ("1234", "pin_trivial"),
        ("4321", "pin_trivial"),
        ("7890", "pin_trivial"),
        ("0987", "pin_trivial"),
        ("23456789", "pin_trivial"),
        ("2580", None),
        ("1357", None),
        ("1212", None),
        ("01234568", None),
    ],
)
def test_pin_rules(pin, problem) -> None:
    assert pin_problem(pin) == problem


def test_production_parameters() -> None:
    """Parametry produkcyjne z projektu (testy podmieniają je fixture'em)."""
    text = Path(pins_module.__file__).read_text(encoding="utf-8")
    assert "SCRYPT_N = 2**14" in text
    assert "SCRYPT_R = 8" in text
    assert "SCRYPT_P = 1" in text
    assert "SCRYPT_DKLEN = 32" in text
    assert "SALT_BYTES = 16" in text


def test_record_has_salt_hash_and_params(freezer) -> None:
    from homeassistant.util import dt as dt_util

    record = new_record("2580", dt_util.now())
    assert len(base64.b64decode(record["salt"])) == 16
    assert len(base64.b64decode(record["hash"])) == 32
    assert (record["n"], record["r"], record["p"]) == (16, 1, 1)
    assert "2580" not in json.dumps(record)
    assert record_matches(record, "2580")
    assert not record_matches(record, "2581")
    other = new_record("2580", dt_util.now())
    assert other["salt"] != record["salt"]
    assert other["hash"] != record["hash"]


def test_old_parameters_still_verify(monkeypatch) -> None:
    """Każdy PIN pamięta swoje parametry: podniesienie N nie łamie starych."""
    from homeassistant.util import dt as dt_util

    record = new_record("2580", dt_util.now())
    monkeypatch.setattr(pins_module, "SCRYPT_N", 32)
    assert record_matches(record, "2580")
    assert new_record("2580", dt_util.now())["n"] == 32


def test_lock_lengths() -> None:
    assert [lock_seconds(level) for level in range(1, 8)] == [
        60, 120, 240, 480, 900, 900, 900,
    ]


async def test_admin_sets_pins_for_everybody(hass, users, loaded) -> None:
    await give_pins(hass, users)
    manager = manager_of(loaded)
    assert set(manager.pins) == {users.admin.id, users.anna.id, users.marek.id, users.tablet.id}
    stored = json.dumps(manager.pins)
    for pin in ("2580", "1357", "8642", "9157"):
        assert pin not in stored


@pytest.mark.parametrize(("pin", "key"), [("12", "pin_format"), ("1111", "pin_trivial")])
async def test_rules_refused(hass, users, loaded, pin, key) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.admin, users.anna, pin)
    assert err.value.translation_key == key
    assert not manager_of(loaded).has_pin(users.anna.id)


async def test_unique_pins_admin_collision_not_counted(hass, users, loaded) -> None:
    await set_pin(hass, users.admin, users.anna, "1357")
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.admin, users.marek, "1357")
    assert err.value.translation_key == "pin_taken"
    manager = manager_of(loaded)
    assert not manager.has_pin(users.marek.id)
    assert manager.lockouts == {}
    # The same PIN again for its owner is not a collision.
    await set_pin(hass, users.admin, users.anna, "1357")


async def test_user_sets_only_own_pin(hass, users, loaded) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.anna, users.marek, "2468")
    assert err.value.translation_key == "own_pin_only"
    await set_pin(hass, users.anna, users.anna, "2468")
    assert manager_of(loaded).has_pin(users.anna.id)


async def test_user_needs_current_pin(hass, users, loaded) -> None:
    await set_pin(hass, users.anna, users.anna, "2468")
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.anna, users.anna, "3579")
    assert err.value.translation_key == "current_pin_required"
    await set_pin(hass, users.anna, users.anna, "3579", current_pin="2468")
    record = manager_of(loaded).pins[users.anna.id]
    assert record_matches(record, "3579")


async def test_g2_wrong_current_pin_counts(hass, users, loaded) -> None:
    await set_pin(hass, users.anna, users.anna, "2468")
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.anna, users.anna, "3579", current_pin="1111")
    assert err.value.translation_key == "wrong_current_pin"
    assert manager_of(loaded).lockouts[users.anna.id]["nieudane"] == 1


async def test_g2_user_collision_counts_and_locks(hass, users, loaded, scrypt_calls) -> None:
    await set_pin(hass, users.admin, users.marek, "8642")
    for attempt in range(1, 5):
        with pytest.raises(ServiceValidationError) as err:
            await set_pin(hass, users.anna, users.anna, "8642")
        assert err.value.translation_key == "pin_taken"
        assert manager_of(loaded).lockouts[users.anna.id]["nieudane"] == attempt
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.anna, users.anna, "8642")
    assert err.value.translation_key == "locked_out"

    calls = scrypt_calls.calls
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, users.anna, users.anna, "9753")
    assert err.value.translation_key == "locked_out"
    assert scrypt_calls.calls == calls
    assert not manager_of(loaded).has_pin(users.anna.id)


async def test_set_pin_needs_user(hass, users, loaded) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await set_pin(hass, None, users.anna, "2468")
    assert err.value.translation_key == "user_required"


async def test_set_pin_unknown_user(hass, users, loaded) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "set_pin", users.admin, {"user_id": "nie-ma", "pin": "2468"})
    assert err.value.translation_key == "unknown_user"


async def test_admin_clears_pin(hass, users, loaded) -> None:
    await give_pins(hass, users)
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "clear_pin", users.anna, {"user_id": users.marek.id})
    assert err.value.translation_key == "admin_required"
    with pytest.raises(ServiceValidationError) as err:
        await service(hass, "clear_pin", None, {"user_id": users.marek.id})
    assert err.value.translation_key == "user_required"
    await service(hass, "clear_pin", users.admin, {"user_id": users.marek.id})
    assert not manager_of(loaded).has_pin(users.marek.id)


async def test_deleted_user_pin_removed(hass, users, loaded) -> None:
    await give_pins(hass, users)
    await hass.auth.async_remove_user(users.marek)
    await hass.async_block_till_done()
    assert not manager_of(loaded).has_pin(users.marek.id)
    assert manager_of(loaded).has_pin(users.anna.id)
