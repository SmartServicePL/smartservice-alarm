# Changelog

## 1.3.0

- New websocket command `smartservice_alarm/check_pin` (`pin`, optional
  `entity_id`) for a dashboard card's PIN-protected view: it answers
  `{"wynik": "poprawny", "user_id", "osoba"}`,
  `{"wynik": "niepoprawny", "pozostalo"}` or
  `{"wynik": "zablokowany", "do"}`. Wrong PINs count together with arming
  (the same account and whole-panel locks); it changes nothing else.
  A websocket command and not an action, so the PIN never goes into a
  `call_service` event or the recorder's database.
- Logbook: `wejscie_bezpieczenstwo` (*Piotr: entered Security*) and
  `wejscie_bezpieczenstwo_nieudane` (*Failed attempt to enter Security*,
  without a name).

## 1.2.0

- One sensor triggers the alarm at most 3 times in one arming. Its next
  triggers are bypassed until disarming; the first bypassed one fires
  `czujka_pominieta` with the sensor's name (once) and the attribute
  `czujniki_pominiete` lists it. Disarming and a new arming forget the count.
- A start of Home Assistant while the panel guarded (exit delay, armed, entry
  delay or alarm) fires `powrot_po_przerwie` once Home Assistant has started:
  the break in minutes (`przerwa_min`, when known), the state before and
  after. While it guards, the panel writes the moment it last ran every
  minute and at Home Assistant's stop.

## 1.1.0

- The sensors checked when arming are checked again at the end of the exit
  delay; open or without a reading: the panel goes back to disarmed and
  fires `odmowa_uzbrojenia` with their names.
- The options change only while the panel is disarmed; a change fires
  `ustawienia` (the logbook names the changed settings).
- A new entry's alarm duration is 10 minutes (was 30).
- One wrong-code counter for the whole panel: 15 wrong codes from several
  accounts within 15 minutes lock every account except administrators for
  15 minutes (an administrator's unlock ends it).
- README: what the alarm is (designed after PN-EN 50131 grade 2, not a
  certified control panel).

## 1.0.2

- New Smart Service logo in the integration icon and logo (light and dark).

## 1.0.1

- Integration icon and logo (light and dark) for Home Assistant and HACS.

## 1.0.0

- Alarm panel with states disarmed, arming, armed away / home / night,
  pending and triggered; modes switched on in the options.
- Personal PIN per Home Assistant user, stored only as a scrypt hash with a
  salt per user; unique PINs; PIN rules (4–8 digits, no trivial PINs).
- Lockout per calling account: 5 wrong PINs → 60 s, doubling up to 15 min,
  kept across restarts. A correct PIN does not clear the count of wrong PINs;
  it expires after 15 minutes without a wrong PIN, and the lockout length
  drops one step per day without a wrong PIN.
- Exit delay, entry delay, alarm duration with return to the armed mode.
- Automation may disarm without a PIN only its own night arming with no alarm
  since.
- Optional PIN for arming; a given PIN must be correct.
- Sensors checked on every arming ("Close: …", "No reading: …").
- Actions `set_pin`, `clear_pin`, `unlock`, `status` (response data) and
  `trigger` with the sensor name.
- Events `smartservice_alarm_event`, logbook texts, diagnostics without
  salts or hashes.
- English and Polish.
- `tools/bench_scrypt.py` to measure the PIN check time.
