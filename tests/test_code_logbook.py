"""1.5.0 (K-1, review 15.11): the silent alarm leaves no trace in the logbook.

An automation on the integration's code event, as the README tells (no
condition of its own, ``przymus`` checked in its actions), leaves the same
logbook entries whether the PIN or the duress PIN disarmed - read by an
ordinary account, as anybody logged in can.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, mock_component
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.smartservice_alarm.const import EVENT_CODE

from .conftest import alarm, give_pins, service

NO_DELAYS = {"exit_delay": 0, "entry_delay": 0}
DURESS = "7314"
SILENT = {
    "alias": "Smart Service Alarm",
    "triggers": [{"trigger": "event", "event_type": EVENT_CODE}],
    "actions": [
        {
            "if": [
                {"condition": "template", "value_template": "{{ trigger.event.data.przymus }}"}
            ],
            "then": [{"event": "smartservice_test_cichy"}],
        }
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder before Home Assistant starts (it is set up before hass)."""
    return


async def _reader(hass, hass_ws_client, user):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _send(client, kind: str, **fields: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": kind, **fields})
    return await client.receive_json()


@pytest.mark.parametrize("entry_options", [NO_DELAYS])
async def test_the_logbook_is_the_same_for_both_pins(
    hass, users, loaded, hass_ws_client
) -> None:
    pins = await give_pins(hass, users)
    await service(
        hass, "set_pin", users.admin,
        {"user_id": users.piotr.id, "pin": DURESS, "rodzaj": "przymus"},
    )
    # The logbook's frontend panel is not part of the test requirements.
    mock_component(hass, "frontend")
    assert await async_setup_component(hass, "logbook", {})
    assert await async_setup_component(hass, "automation", {"automation": SILENT})
    await hass.async_block_till_done()
    silent: list[Any] = []
    hass.bus.async_listen("smartservice_test_cichy", silent.append)
    reader = await _reader(hass, hass_ws_client, users.adam)

    async def window(code: str) -> list[tuple[Any, ...]]:
        await alarm(hass, "alarm_arm_away", users.adam, pins["adam"])
        await hass.async_block_till_done()
        await async_wait_recording_done(hass)
        start = dt_util.utcnow()
        await alarm(hass, "alarm_disarm", users.piotr, code)
        await hass.async_block_till_done()
        await async_wait_recording_done(hass)
        answer = await _send(
            reader, "logbook/get_events",
            start_time=start.isoformat(), end_time=dt_util.utcnow().isoformat(),
        )
        assert answer["success"] is True, answer
        keys = ("name", "message", "domain", "entity_id", "state")
        keys += ("context_entity_id", "context_state")
        return sorted(tuple(str(row.get(key) or "") for key in keys) for row in answer["result"])

    normal = await window(pins["piotr"])
    assert silent == []
    forced = await window(DURESS)
    # The silent alarm went - and the logbook is the same as with the PIN.
    assert len(silent) == 1
    assert forced == normal
    assert any(row[2] == "automation" for row in normal), normal
    assert all("przymus" not in str(row) for row in forced)
