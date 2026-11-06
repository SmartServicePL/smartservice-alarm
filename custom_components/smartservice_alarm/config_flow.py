"""Config and options flow of Smart Service Alarm."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from . import events
from .const import (
    ACTION_OPTIONS,
    CONF_ARM_AWAY,
    CONF_ARM_HOME,
    CONF_ARM_NIGHT,
    CONF_CODE_ARM_REQUIRED,
    CONF_ENTRY_DELAY,
    CONF_EXIT_DELAY,
    CONF_KIND,
    CONF_NAME,
    CONF_PANEL_ON,
    CONF_SENSORS,
    CONF_TRIGGER_TIME,
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    DOMAIN,
    KIND_PANEL,
    KIND_PINS,
)
from .pins import pins_only

INT_OPTIONS = (CONF_EXIT_DELAY, CONF_ENTRY_DELAY, CONF_TRIGGER_TIME)


def _number(maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0 if unit == "s" else 1,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


KIND_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[KIND_PANEL, KIND_PINS],
        translation_key=CONF_KIND,
        mode=selector.SelectSelectorMode.LIST,
    )
)


class SmartServiceAlarmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single step: the name and the kind (alarm panel or only PINs)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self._async_current_entries()
        if any(pins_only(entry.data) for entry in existing):
            # One place for the PINs: the entry with only PINs becomes the
            # alarm panel in its options, keeping them.
            return self.async_abort(reason="pins_only_exists")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            only_pins = user_input.get(CONF_KIND) == KIND_PINS
            if only_pins and existing:
                return self.async_abort(reason="panel_keeps_pins")
            if name:
                if only_pins:
                    return self.async_create_entry(
                        title=name, data={CONF_NAME: name, CONF_KIND: KIND_PINS}
                    )
                return self.async_create_entry(
                    title=name,
                    data={CONF_NAME: name},
                    options={**DEFAULT_OPTIONS, CONF_SENSORS: []},
                )
            errors[CONF_NAME] = "empty_name"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                    vol.Required(CONF_KIND, default=KIND_PANEL): KIND_SELECTOR,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartServiceAlarmOptionsFlow()


class SmartServiceAlarmOptionsFlow(OptionsFlowWithReload):
    """Modes, delays, code for arming and sensors checked when arming."""

    def _panel_entity(self) -> str | None:
        registry = er.async_get(self.hass)
        for item in er.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if item.domain == "alarm_control_panel":
                return item.entity_id
        return None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if pins_only(self.config_entry.data):
            return await self.async_step_piny(user_input)
        errors: dict[str, str] = {}
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        if user_input is not None:
            panel = self._panel_entity()
            panel_state = self.hass.states.get(panel) if panel else None
            if panel_state is not None and panel_state.state != "disarmed":
                # Z17 (30.10): the settings change only while disarmed.
                errors["base"] = "not_disarmed"
            elif not any(
                user_input.get(key) for key in (CONF_ARM_AWAY, CONF_ARM_HOME, CONF_ARM_NIGHT)
            ):
                errors["base"] = "no_mode"
            else:
                options = {**DEFAULT_OPTIONS, **user_input}
                for key in INT_OPTIONS:
                    options[key] = int(options[key])
                changed = sorted(
                    key for key in options if options[key] != current.get(key)
                )
                if changed:
                    await events.async_fire(
                        self.hass, panel, ACTION_OPTIONS, None, zmienione=changed
                    )
                return self.async_create_entry(data=options)
            current = {**current, **user_input}

        schema = vol.Schema(
            {
                vol.Required(CONF_ARM_AWAY, default=current[CONF_ARM_AWAY]): bool,
                vol.Required(CONF_ARM_HOME, default=current[CONF_ARM_HOME]): bool,
                vol.Required(CONF_ARM_NIGHT, default=current[CONF_ARM_NIGHT]): bool,
                vol.Required(
                    CONF_EXIT_DELAY, default=current[CONF_EXIT_DELAY]
                ): _number(3600, "s"),
                vol.Required(
                    CONF_ENTRY_DELAY, default=current[CONF_ENTRY_DELAY]
                ): _number(3600, "s"),
                vol.Required(
                    CONF_TRIGGER_TIME, default=current[CONF_TRIGGER_TIME]
                ): _number(1440, "min"),
                vol.Required(
                    CONF_CODE_ARM_REQUIRED, default=current[CONF_CODE_ARM_REQUIRED]
                ): bool,
                vol.Optional(
                    CONF_SENSORS, default=list(current[CONF_SENSORS])
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_piny(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """An entry with only PINs: turn on the alarm panel (the PINs stay).

        One way only - a panel never goes back to only PINs (its automations
        and dashboards would lose the panel).
        """
        if user_input is not None:
            if not user_input.get(CONF_PANEL_ON):
                return self.async_create_entry(data=dict(self.config_entry.options))
            data = {
                key: value
                for key, value in self.config_entry.data.items()
                if key != CONF_KIND
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(data={**DEFAULT_OPTIONS, CONF_SENSORS: []})
        return self.async_show_form(
            step_id="piny",
            data_schema=vol.Schema({vol.Required(CONF_PANEL_ON, default=False): bool}),
        )
