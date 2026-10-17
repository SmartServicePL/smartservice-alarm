"""Tłumaczenia: komplet kluczy PL, placeholdery i każdy użyty klucz błędu."""

from __future__ import annotations

import json
from pathlib import Path
import re

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "smartservice_alarm"


def load(name: str) -> dict:
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def keys(data: dict, prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, value in data.items():
        found.add(prefix + key)
        if isinstance(value, dict):
            found |= keys(value, f"{prefix}{key}.")
    return found


def test_english_matches_strings() -> None:
    assert load("translations/en.json") == load("strings.json")


def test_polish_has_every_key() -> None:
    assert keys(load("translations/pl.json")) == keys(load("strings.json"))


def test_every_error_key_is_translated() -> None:
    literals: set[str] = set()
    raised: set[str] = set()
    for path in INTEGRATION.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        literals |= set(re.findall(r'"([a-z_]+)"', text))
        raised |= set(re.findall(r'alarm_error\(\s*"([a-z_]+)"', text))
    strings = load("strings.json")
    polish = load("translations/pl.json")
    exceptions = set(strings["exceptions"])
    assert raised <= exceptions
    assert exceptions <= literals
    for key in exceptions:
        english = strings["exceptions"][key]["message"]
        translated = polish["exceptions"][key]["message"]
        assert set(re.findall(r"{(\w+)}", english)) == set(
            re.findall(r"{(\w+)}", translated)
        )


def test_polish_messages_from_project() -> None:
    messages = {k: v["message"] for k, v in load("translations/pl.json")["exceptions"].items()}
    assert messages["wrong_pin"] == "Błędny PIN."
    assert messages["locked_out"] == "Zbyt wiele błędnych prób. Spróbuj o {godzina}."
    assert messages["pin_required"] == "Podaj PIN."
    assert messages["mode_disabled"] == "Ten tryb jest wyłączony w ustawieniach alarmu."
    assert messages["pin_taken"] == "Ten PIN ma już inny domownik — wybierz inny."
    assert messages["pin_format"] == "PIN to od 4 do 8 cyfr."
    assert messages["sensors_open"] == "Zamknij: {czujniki}"
    assert messages["sensors_unavailable"] == "Brak odczytu: {czujniki}"


def test_services_yaml_matches_strings() -> None:
    import yaml

    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))
    strings = load("strings.json")["services"]
    assert set(services) == set(strings)
    for name, spec in services.items():
        assert set(spec.get("fields", {})) == set(strings[name]["fields"])
