# Changelog

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
