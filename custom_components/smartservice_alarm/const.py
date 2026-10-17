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
DEFAULT_OPTIONS: Final = {
    CONF_ARM_AWAY: True,
    CONF_ARM_HOME: True,
    CONF_ARM_NIGHT: True,
    CONF_EXIT_DELAY: 60,
    CONF_ENTRY_DELAY: 30,
    CONF_TRIGGER_TIME: 30,
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
