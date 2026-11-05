"""The README says what the alarm is - the approved sentence (30.10.2026,
variant B), word for word in both languages' files, never shortened."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
INFO = (
    "Smart Service Alarm jest projektowany według zasad PN-EN 50131 (stopień 2), "
    "ale nie jest certyfikowaną centralą alarmową. Nie zastępuje profesjonalnego "
    "systemu alarmowego ani monitoringu agencji ochrony."
)


def test_both_readmes_say_what_the_alarm_is_word_for_word() -> None:
    for name in ("README.md", "README_PL.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert text.count(f"> {INFO}\n") == 1, name
