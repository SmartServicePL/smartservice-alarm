"""1.3.0: sprawdzenie PIN-u przy wejściu do „Bezpieczeństwo” a baza recordera.

Osobny moduł: recorder musi powstać przed Home Assistant (fixture
mock_recorder_before_hass), a wspólne fixture'y uruchamiają HA wcześniej.
"""

from __future__ import annotations

import re

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.db_schema import EventData, StateAttributes, States
from homeassistant.components.recorder.util import session_scope
from homeassistant.core import HomeAssistant

from custom_components.smartservice_alarm import pins as pins_module
from custom_components.smartservice_alarm.const import WS_CHECK_PIN

from .conftest import make_entry, set_pin

WRONG = "4826"


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder) -> None:
    """The recorder (in-memory SQLite) starts before Home Assistant."""


def _alone(pin: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z]){pin}(?![0-9A-Za-z])")


def _database_text(hass: HomeAssistant) -> str:
    with session_scope(hass=hass, read_only=True) as session:
        rows = [row[0] or "" for row in session.query(EventData.shared_data).all()]
        rows += [row[0] or "" for row in session.query(StateAttributes.shared_attrs).all()]
        rows += [row[0] or "" for row in session.query(States.state).all()]
    return "\n".join(rows)


async def test_nothing_with_the_pin_reaches_the_recorder(
    recorder_mock, hass, users, hass_ws_client
) -> None:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # PINs set straight in the integration: set_pin is an action, so its PIN
    # would itself reach the database (the control below).
    pins = {"piotr": "1357", "adam": "8642"}
    for name, pin in pins.items():
        await entry.runtime_data.async_set_pin(
            getattr(users, name).id,
            pin,
            admin=True,
            bucket=users.admin.id,
            current_pin=None,
            context=None,
        )
    refresh = await hass.auth.async_create_refresh_token(users.piotr, CLIENT_ID)
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))

    for pin in (pins["piotr"], *[WRONG] * 5):
        await client.send_json_auto_id({"type": WS_CHECK_PIN, "pin": pin})
        assert (await client.receive_json())["success"] is True
    # Control: a PIN given to a service does reach the database - the reason
    # why the entry check is a websocket command.
    await set_pin(hass, users.admin, users.adam, "3691")
    await async_wait_recording_done(hass)

    text = await get_instance(hass).async_add_executor_job(_database_text, hass)
    # The entry events themselves are recorded (the logbook shows them).
    assert "wejscie_bezpieczenstwo" in text
    assert _alone("3691").search(text)
    for pin in (pins["piotr"], WRONG):
        assert not _alone(pin).search(text)
    assert pins_module.pin_problem(WRONG) is None
