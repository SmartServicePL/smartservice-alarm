"""Kreator (sama nazwa) i opcje centrali."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smartservice_alarm.const import DEFAULT_OPTIONS, DOMAIN

from .conftest import ENTITY, make_entry


async def test_user_step_creates_entry_with_defaults(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "  "}
    )
    assert result["errors"] == {"name": "empty_name"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Dom"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dom"
    assert result["data"] == {"name": "Dom"}
    assert result["options"] == DEFAULT_OPTIONS
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "disarmed"
    assert state.attributes["code_format"] == "number"
    assert state.attributes["code_arm_required"] is False


async def test_options_flow_saves_and_reloads(hass, users) -> None:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    options = {
        "arm_away": False,
        "arm_home": False,
        "arm_night": False,
        "exit_delay": 10,
        "entry_delay": 5,
        "trigger_time": 2,
        "code_arm_required": True,
        "sensors": [],
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_mode"}

    options |= {"arm_away": True, "sensors": ["binary_sensor.okno_salon"]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == options
    assert isinstance(entry.options["exit_delay"], int)
    assert hass.states.get(ENTITY).attributes["code_arm_required"] is True
