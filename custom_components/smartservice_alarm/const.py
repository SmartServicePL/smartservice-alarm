"""Constants of Smart Service Alarm."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smartservice_alarm"
EVENT_ALARM: Final = "smartservice_alarm_event"

STORAGE_VERSION: Final = 1

CONF_NAME: Final = "name"
CONF_ARM_AWAY: Final = "arm_away"
CONF_ARM_HOME: Final = "arm_home"
CONF_ARM_NIGHT: Final = "arm_night"
CONF_EXIT_DELAY: Final = "exit_delay"
CONF_ENTRY_DELAY: Final = "entry_delay"
CONF_TRIGGER_TIME: Final = "trigger_time"
CONF_CODE_ARM_REQUIRED: Final = "code_arm_required"
CONF_SENSORS: Final = "sensors"

DEFAULT_NAME: Final = "Alarm"
# 1.4.0: an entry can keep only the users'
# PINs, without an alarm panel - for the PIN of a dashboard view in a home
# without this alarm. Stored in the entry's data; a missing key is a panel.
CONF_KIND: Final = "rodzaj"
KIND_PANEL: Final = "centrala"
KIND_PINS: Final = "piny"
CONF_PANEL_ON: Final = "centrala"
DEFAULT_OPTIONS: Final = {
    CONF_ARM_AWAY: True,
    CONF_ARM_HOME: True,
    CONF_ARM_NIGHT: True,
    CONF_EXIT_DELAY: 60,
    CONF_ENTRY_DELAY: 30,
    # Z26 (30.10): 10 minutes for a new entry (the sirens sound their own time).
    CONF_TRIGGER_TIME: 10,
    CONF_CODE_ARM_REQUIRED: False,
    CONF_SENSORS: [],
}

# Extra state attributes (never any PIN data).
ATTR_CHANGE_SOURCE: Final = "zmiana_przez"
ATTR_ARMED_BY_AUTOMATION: Final = "uzbrojenie_przez_automat"
ATTR_TRIGGER_SENSOR: Final = "czujnik_wyzwalajacy"
ATTR_MODE: Final = "tryb"
ATTR_COUNTDOWN_END: Final = "koniec_odliczania"

SOURCE_USER: Final = "uzytkownik"
SOURCE_AUTOMATION: Final = "automatyzacja"
SOURCE_TRIGGER: Final = "wyzwolenie"

CHANGED_BY_AUTOMATION: Final = "Automatyzacja"

# Service names and fields.
SERVICE_SET_PIN: Final = "set_pin"
SERVICE_CLEAR_PIN: Final = "clear_pin"
SERVICE_UNLOCK: Final = "unlock"
SERVICE_STATUS: Final = "status"
SERVICE_TRIGGER: Final = "trigger"

ATTR_USER_ID: Final = "user_id"
ATTR_PIN: Final = "pin"
ATTR_CURRENT_PIN: Final = "current_pin"
ATTR_SENSOR: Final = "czujnik"

# Event actions (field "akcja" of smartservice_alarm_event).
ACTION_ARM: Final = "uzbrojenie"
ACTION_DISARM: Final = "rozbrojenie"
ACTION_WRONG_CODE: Final = "zly_kod"
ACTION_LOCKOUT: Final = "blokada"
ACTION_UNLOCK: Final = "odblokowanie"
ACTION_TRIGGER: Final = "wyzwolenie"
ACTION_PIN_SET: Final = "pin_ustawiony"
ACTION_PIN_CLEARED: Final = "pin_usuniety"
# Z13 (30.10): at the end of the exit delay a listed sensor was open or had
# no reading - the panel went back to disarmed.
ACTION_ARM_REFUSED: Final = "odmowa_uzbrojenia"
# Z17 (30.10): the options changed (only while disarmed).
ACTION_OPTIONS: Final = "ustawienia"
# Z25: one sensor triggered the alarm 3 times in one arming - its next
# triggers are bypassed until disarming (told once).
ACTION_SENSOR_BYPASSED: Final = "czujka_pominieta"
# Z21: Home Assistant started again while the panel guarded - how long it was
# down (minutes, when known) and the state after the countdowns caught up.
ACTION_BACK: Final = "powrot_po_przerwie"
# 1.3.0: the PIN checked when entering the panel's "Security" view
# (websocket command, never a service - see WS_CHECK_PIN).
ACTION_ENTRY: Final = "wejscie_bezpieczenstwo"
ACTION_ENTRY_FAILED: Final = "wejscie_bezpieczenstwo_nieudane"

# Websocket command, not a service: Home Assistant puts the data of every
# service call into a call_service event, and the recorder writes it to its
# database - a PIN must never get there.
WS_CHECK_PIN: Final = "smartservice_alarm/check_pin"
# 1.4.0: every PIN goes this way (the actions stay for automations).
WS_ARM: Final = "smartservice_alarm/arm"
WS_DISARM: Final = "smartservice_alarm/disarm"
WS_SET_PIN: Final = "smartservice_alarm/set_pin"
WS_CLEAR_PIN: Final = "smartservice_alarm/clear_pin"

# Z25: at most this many triggers of one sensor in one arming.
MAX_TRIGGERS_PER_SENSOR: Final = 3
# Extra attribute: the sensors bypassed until disarming (names).
ATTR_BYPASSED: Final = "czujniki_pominiete"
