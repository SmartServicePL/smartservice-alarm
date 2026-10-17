"""Alarm control panel of Smart Service Alarm."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from . import events
from .const import (
    ACTION_ARM,
    ACTION_DISARM,
    ACTION_TRIGGER,
    ATTR_ARMED_BY_AUTOMATION,
    ATTR_CHANGE_SOURCE,
    ATTR_COUNTDOWN_END,
    ATTR_MODE,
    ATTR_TRIGGER_SENSOR,
    CHANGED_BY_AUTOMATION,
    CONF_ARM_AWAY,
    CONF_ARM_HOME,
    CONF_ARM_NIGHT,
    CONF_CODE_ARM_REQUIRED,
    CONF_ENTRY_DELAY,
    CONF_EXIT_DELAY,
    CONF_SENSORS,
    CONF_TRIGGER_TIME,
    DEFAULT_OPTIONS,
    SOURCE_AUTOMATION,
    SOURCE_TRIGGER,
    SOURCE_USER,
)
from .pins import PinManager, alarm_error, bucket_for

_LOGGER = logging.getLogger(__name__)

# The integration serialises code checks itself.
PARALLEL_UPDATES = 0

Alarm = AlarmControlPanelState

MODE_OPTIONS = {
    Alarm.ARMED_AWAY: CONF_ARM_AWAY,
    Alarm.ARMED_HOME: CONF_ARM_HOME,
    Alarm.ARMED_NIGHT: CONF_ARM_NIGHT,
}

# Keys of the persisted panel state.
S_STATE = "stan"
S_MODE = "tryb"
S_BY_AUTOMATION = "przez_automat"
S_ALARM_SINCE_ARMING = "alarm_od_uzbrojenia"
S_CHANGED_BY = "changed_by"
S_SOURCE = "zmiana_przez"
S_SENSOR = "czujnik"
S_END = "koniec"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the alarm panel of this entry."""
    async_add_entities([SmartServiceAlarmPanel(entry, entry.runtime_data)])


class SmartServiceAlarmPanel(AlarmControlPanelEntity):
    """Alarm panel: per-user PINs, exit / entry delay, trigger duration."""

    _attr_should_poll = False
    _attr_code_format = CodeFormat.NUMBER
    # All three modes are always declared so that a call for a mode that is
    # switched off in the options gets this integration's own message.
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_NIGHT
        | AlarmControlPanelEntityFeature.TRIGGER
    )

    def __init__(self, entry: ConfigEntry, pins: PinManager) -> None:
        self._entry = entry
        self._pins = pins
        self._options: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title
        self._attr_code_arm_required = bool(self._options[CONF_CODE_ARM_REQUIRED])
        self._unsub_timer: Callable[[], None] | None = None

    # -- persisted state -------------------------------------------------

    @property
    def _s(self) -> dict[str, Any]:
        return self._pins.state

    @callback
    def _async_read_entity_options(self) -> None:
        """Ignore a "default code" from the entity settings.

        A default code would be a PIN stored in plain text and would let any
        call disarm without a PIN, so this panel never uses it.
        """
        self._alarm_control_panel_option_default_code = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_CHANGE_SOURCE: self._s.get(S_SOURCE),
            ATTR_ARMED_BY_AUTOMATION: bool(self._s.get(S_BY_AUTOMATION, False)),
            ATTR_TRIGGER_SENSOR: self._s.get(S_SENSOR),
            ATTR_MODE: self._s.get(S_MODE),
            ATTR_COUNTDOWN_END: self._s.get(S_END),
        }

    def _end(self) -> datetime | None:
        value = self._s.get(S_END)
        return dt_util.parse_datetime(value) if value else None

    @callback
    def _sync_attrs(self) -> None:
        self._attr_alarm_state = Alarm(self._s.get(S_STATE, Alarm.DISARMED))
        self._attr_changed_by = self._s.get(S_CHANGED_BY)

    async def async_added_to_hass(self) -> None:
        """Restore the state saved before a restart and resume timers."""
        await super().async_added_to_hass()
        self._s.setdefault(S_STATE, Alarm.DISARMED)
        self._restore(dt_util.utcnow())
        self._sync_attrs()
        await self._pins.async_save()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()

    def _restore(self, now: datetime) -> None:
        state = self._s.get(S_STATE)
        mode = self._s.get(S_MODE)
        if state not in {s.value for s in Alarm} or (
            state in (Alarm.ARMING, Alarm.PENDING, Alarm.TRIGGERED) and mode not in MODE_OPTIONS
        ):
            self._s.clear()
            self._s[S_STATE] = Alarm.DISARMED
            return
        end = self._end()
        if state in (Alarm.ARMING, Alarm.PENDING) and (end is None or end <= now):
            if state == Alarm.ARMING:
                self._s.update({S_STATE: mode, S_END: None})
            else:
                trigger_end = (end or now) + self._trigger_time()
                self._s.update({S_STATE: Alarm.TRIGGERED, S_END: trigger_end.isoformat()})
            state = self._s[S_STATE]
            end = self._end()
        if state == Alarm.TRIGGERED and (end is None or end <= now):
            self._s.update({S_STATE: mode, S_END: None})
            end = None
        if end is not None:
            self._schedule(end)

    # -- timers ----------------------------------------------------------

    def _trigger_time(self) -> timedelta:
        return timedelta(minutes=int(self._options[CONF_TRIGGER_TIME]))

    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    def _schedule(self, end: datetime) -> None:
        self._cancel_timer()
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_timer_done, end
        )

    async def _async_timer_done(self, now: datetime) -> None:
        self._unsub_timer = None
        state = self._s.get(S_STATE)
        mode = self._s.get(S_MODE)
        if state == Alarm.ARMING:
            await self._async_apply({S_STATE: mode})
        elif state == Alarm.PENDING:
            await self._async_apply(
                {S_STATE: Alarm.TRIGGERED},
                end=dt_util.utcnow() + self._trigger_time(),
            )
        elif state == Alarm.TRIGGERED:
            await self._async_apply({S_STATE: mode})

    async def _async_apply(
        self,
        changes: dict[str, Any],
        *,
        end: datetime | None = None,
        context: Context | None = None,
    ) -> None:
        """Change state, (re)start the countdown, write and persist."""
        self._cancel_timer()
        self._s.update(changes)
        self._s[S_END] = end.isoformat() if end else None
        if end is not None:
            self._schedule(end)
        self._sync_attrs()
        if context is not None:
            self.async_set_context(context)
        self.async_write_ha_state()
        await self._pins.async_save()

    # -- helpers ---------------------------------------------------------

    async def _actor_name(self, owner_id: str | None, user_id: str | None) -> str:
        name = await events.async_user_name(self.hass, owner_id or user_id)
        return name or CHANGED_BY_AUTOMATION

    def _check_sensors(self) -> None:
        """Refuse arming when a listed sensor is open or has no reading."""
        opened: list[str] = []
        missing: list[str] = []
        for entity_id in self._options.get(CONF_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                missing.append(state.name if state else entity_id)
            elif state.state == STATE_ON:
                opened.append(state.name)
        if opened:
            raise alarm_error("sensors_open", czujniki=", ".join(opened))
        if missing:
            raise alarm_error("sensors_unavailable", czujniki=", ".join(missing))

    # -- arming ----------------------------------------------------------

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._async_arm(Alarm.ARMED_AWAY, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._async_arm(Alarm.ARMED_HOME, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._async_arm(Alarm.ARMED_NIGHT, code)

    async def _async_arm(self, mode: AlarmControlPanelState, code: str | None) -> None:
        # The service helper sets the call context right before calling the
        # method; read it before the first await.
        context = self._context
        user_id = context.user_id if context else None

        if not self._options.get(MODE_OPTIONS[mode]):
            raise alarm_error("mode_disabled")
        if self._s.get(S_STATE) in (Alarm.PENDING, Alarm.TRIGGERED):
            raise alarm_error("disarm_first")

        owner_id: str | None = None
        if code:
            owner_id = await self._pins.async_check_code(bucket_for(user_id), code, context)
        elif self.code_arm_required:
            raise alarm_error("pin_required")

        if self._s.get(S_STATE) == mode:
            return
        self._check_sensors()

        exit_delay = int(self._options[CONF_EXIT_DELAY])
        changes = {
            S_STATE: Alarm.ARMING if exit_delay > 0 else mode,
            S_MODE: mode,
            S_BY_AUTOMATION: user_id is None,
            S_ALARM_SINCE_ARMING: False,
            S_CHANGED_BY: await self._actor_name(owner_id, user_id),
            S_SOURCE: SOURCE_USER if (owner_id or user_id) else SOURCE_AUTOMATION,
            S_SENSOR: None,
        }
        end = dt_util.utcnow() + timedelta(seconds=exit_delay) if exit_delay > 0 else None
        await self._async_apply(changes, end=end, context=context)
        await events.async_fire(
            self.hass,
            self.entity_id,
            ACTION_ARM,
            context,
            owner_id=owner_id,
            caller_id=user_id,
            tryb=mode,
        )

    # -- disarming -------------------------------------------------------

    def _automation_may_disarm(self) -> bool:
        """G1: night arming made by an automation, with no alarm since."""
        return (
            self._s.get(S_STATE) == Alarm.ARMED_NIGHT
            and bool(self._s.get(S_BY_AUTOMATION))
            and not self._s.get(S_ALARM_SINCE_ARMING)
        )

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        context = self._context
        user_id = context.user_id if context else None

        owner_id: str | None = None
        if code:
            owner_id = await self._pins.async_check_code(bucket_for(user_id), code, context)
            source = SOURCE_USER
        elif user_id is None and self._automation_may_disarm():
            source = SOURCE_AUTOMATION
        else:
            raise alarm_error("pin_required")

        previous_mode = self._s.get(S_MODE)
        await self._async_apply(
            {
                S_STATE: Alarm.DISARMED,
                S_MODE: None,
                S_BY_AUTOMATION: False,
                S_ALARM_SINCE_ARMING: False,
                S_CHANGED_BY: await self._actor_name(owner_id, None)
                if owner_id
                else CHANGED_BY_AUTOMATION,
                S_SOURCE: source,
                S_SENSOR: None,
            },
            context=context,
        )
        await events.async_fire(
            self.hass,
            self.entity_id,
            ACTION_DISARM,
            context,
            owner_id=owner_id,
            caller_id=user_id,
            tryb=previous_mode,
        )

    # -- triggering ------------------------------------------------------

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        """Standard alarm_trigger: no code needed, no sensor name."""
        await self._async_trigger(None)

    async def async_trigger_sensor(self, czujnik: str | None = None) -> None:
        """smartservice_alarm.trigger: like alarm_trigger, with a sensor name."""
        await self._async_trigger(czujnik)

    async def _async_trigger(self, sensor: str | None) -> None:
        context = self._context
        user_id = context.user_id if context else None
        state = self._s.get(S_STATE)
        if state not in MODE_OPTIONS:
            # Disarmed, exit delay running, or already pending / triggered.
            _LOGGER.debug("Trigger ignored in state %s", state)
            return
        entry_delay = int(self._options[CONF_ENTRY_DELAY])
        now = dt_util.utcnow()
        changes = {
            S_STATE: Alarm.PENDING if entry_delay > 0 else Alarm.TRIGGERED,
            S_ALARM_SINCE_ARMING: True,
            S_CHANGED_BY: await self._actor_name(None, user_id),
            S_SOURCE: SOURCE_TRIGGER,
            S_SENSOR: sensor,
        }
        end = now + (
            timedelta(seconds=entry_delay) if entry_delay > 0 else self._trigger_time()
        )
        await self._async_apply(changes, end=end, context=context)
        await events.async_fire(
            self.hass,
            self.entity_id,
            ACTION_TRIGGER,
            context,
            caller_id=user_id,
            tryb=self._s.get(S_MODE),
            czujnik=sensor,
        )
