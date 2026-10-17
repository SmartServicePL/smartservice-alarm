"""Wspólne fixture'y: centrala „Dom”, domownicy i szybki scrypt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.core import Context, HomeAssistant

from custom_components.smartservice_alarm import pins as pins_module
from custom_components.smartservice_alarm.const import DEFAULT_OPTIONS, DOMAIN

ENTITY = "alarm_control_panel.dom"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Pozwala ładować integracje z custom_components."""
    return


class ScryptCounter:
    """Liczy wywołania scrypt (każde liczenie skrótu PIN-u)."""

    def __init__(self) -> None:
        self.calls = 0


@pytest.fixture(autouse=True)
def scrypt_calls(monkeypatch) -> ScryptCounter:
    """Lekkie parametry scrypt w testach i licznik wywołań."""
    counter = ScryptCounter()
    original = pins_module.scrypt_hash

    def counting(*args: Any, **kwargs: Any) -> bytes:
        counter.calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pins_module, "SCRYPT_N", 16)
    monkeypatch.setattr(pins_module, "SCRYPT_R", 1)
    monkeypatch.setattr(pins_module, "scrypt_hash", counting)
    return counter


@dataclass
class Users:
    admin: MockUser
    anna: MockUser
    marek: MockUser
    tablet: MockUser


@pytest.fixture
async def users(hass: HomeAssistant) -> Users:
    """Administrator Zbigniew, zwykli użytkownicy Anna i Marek, konto tabletu."""
    admin_group = await hass.auth.async_get_group(GROUP_ID_ADMIN)
    user_group = await hass.auth.async_get_group(GROUP_ID_USER)
    return Users(
        admin=MockUser(name="Zbigniew", groups=[admin_group]).add_to_hass(hass),
        anna=MockUser(name="Anna", groups=[user_group]).add_to_hass(hass),
        marek=MockUser(name="Marek", groups=[user_group]).add_to_hass(hass),
        tablet=MockUser(name="Tablet salon", groups=[user_group]).add_to_hass(hass),
    )


def make_entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dom",
        data={"name": "Dom"},
        options={**DEFAULT_OPTIONS, **options},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def entry_options() -> dict[str, Any]:
    """Opcje centrali; testy nadpisują je parametryzacją fixture'a."""
    return {}


@pytest.fixture
async def loaded(hass: HomeAssistant, users: Users, entry_options) -> MockConfigEntry:
    """Załadowana centrala „Dom”."""
    entry = make_entry(hass, **entry_options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def ctx(user: MockUser | None) -> Context:
    """Kontekst wywołania: konto użytkownika albo automatyzacja (bez konta)."""
    return Context(user_id=user.id if user else None)


async def alarm(
    hass: HomeAssistant, service: str, user: MockUser | None, code: str | None = None
) -> None:
    """Standardowa usługa alarm_control_panel.* na centrali „Dom”."""
    data: dict[str, Any] = {"entity_id": ENTITY}
    if code is not None:
        data["code"] = code
    await hass.services.async_call(
        ALARM_DOMAIN, service, data, blocking=True, context=ctx(user)
    )


async def service(
    hass: HomeAssistant,
    name: str,
    user: MockUser | None,
    data: dict[str, Any] | None = None,
    *,
    response: bool = False,
) -> Any:
    """Usługa smartservice_alarm.*."""
    return await hass.services.async_call(
        DOMAIN,
        name,
        data or {},
        blocking=True,
        context=ctx(user),
        return_response=response,
    )


async def set_pin(
    hass: HomeAssistant,
    caller: MockUser | None,
    target: MockUser,
    pin: str,
    current_pin: str | None = None,
) -> None:
    data = {"user_id": target.id, "pin": pin}
    if current_pin is not None:
        data["current_pin"] = current_pin
    await service(hass, "set_pin", caller, data)


async def give_pins(hass: HomeAssistant, users: Users) -> dict[str, str]:
    """PIN-y wszystkich domowników ustawione przez administratora."""
    chosen = {"admin": "2580", "anna": "1357", "marek": "8642", "tablet": "9157"}
    for key, pin in chosen.items():
        await set_pin(hass, users.admin, getattr(users, key), pin)
    return chosen


def manager_of(entry: MockConfigEntry) -> pins_module.PinManager:
    return entry.runtime_data
