# Smart Service Alarm

A custom integration for Home Assistant that adds an alarm panel
(`alarm_control_panel`) with a **personal PIN for every Home Assistant user**.
The panel knows who armed and disarmed it, locks an account after wrong PINs
and writes every action to the logbook — never the PIN itself.

[Polski opis — README_PL.md](README_PL.md)

- Free and open source (MIT), works on its own.
- Configured only from the user interface (no YAML).
- English and Polish.

## Installation (HACS)

1. HACS → three dots → **Custom repositories**.
2. Repository: `https://github.com/SmartServicePL/smartservice-alarm`, type **Integration**.
3. Install **Smart Service Alarm** and restart Home Assistant.
4. **Settings → Devices & services → Helpers → Create helper → Smart Service Alarm**
   (or **Add integration** and search for it). Enter a name, for example `Home`;
   the panel becomes `alarm_control_panel.home`.

Manual installation: copy `custom_components/smartservice_alarm` into the
`custom_components` folder of your configuration and restart.

## Panel

| | |
|---|---|
| States | `disarmed`, `arming`, `armed_away`, `armed_home`, `armed_night`, `pending`, `triggered` |
| Code format | number |
| Disarming | always with a user's PIN (one exception below) |
| Arming | PIN optional unless *PIN required for arming* is on; a PIN that is given must be correct |

Flow: arm → `arming` (exit delay) → armed. A trigger while armed →
`pending` (entry delay) → `triggered` (alarm duration) → back to the same
armed mode. A trigger while disarmed or during the exit delay is ignored.

Extra attributes (never any PIN data):

| Attribute | Meaning |
|---|---|
| `changed_by` | name of the PIN owner, the calling user, or `Automatyzacja` |
| `zmiana_przez` | `uzytkownik`, `automatyzacja` or `wyzwolenie` |
| `uzbrojenie_przez_automat` | `true` when the current arming came from a call without a user (automation) |
| `czujnik_wyzwalajacy` | sensor name passed to `smartservice_alarm.trigger` |
| `tryb` | armed mode in effect or being armed |
| `koniec_odliczania` | end of the running exit delay, entry delay or alarm (ISO) |

**Automation disarming at night.** A call without a user (an automation) may
disarm without a PIN only when the panel is `armed_night`, that arming was made
by an automation, and there was no `pending` or `triggered` since. Every other
disarm without a PIN is refused.

## Options

| Option | Default |
|---|---|
| Modes: away / home / night | all on |
| Exit delay | 60 s |
| Entry delay | 30 s |
| Alarm duration, then back to armed | 30 min |
| PIN required for arming | off |
| Sensors checked when arming | none |

Sensors checked when arming are checked on **every** arming, also by
automations. An open sensor (`on`) refuses arming with `Close: <names>`; a
sensor that is `unavailable`, `unknown` or missing refuses it with
`No reading: <names>`. Nothing is bypassed or forced.

## Actions

| Action | Fields | Who |
|---|---|---|
| `smartservice_alarm.set_pin` | `user_id`, `pin`, `current_pin` (optional), `entity_id` (optional) | administrator for anyone; a user only for himself, with `current_pin` when he already has a PIN |
| `smartservice_alarm.clear_pin` | `user_id`, `entity_id` (optional) | administrator |
| `smartservice_alarm.unlock` | `user_id` (or `_bez_konta`), `entity_id` (optional) | administrator |
| `smartservice_alarm.status` | `entity_id` (optional) | administrator; returns `{user_id: {"pin": bool, "zablokowany_do": ISO or null}}` |
| `smartservice_alarm.trigger` | target panel, `czujnik` (optional) | anyone (typically an automation) |

`entity_id` is needed only when more than one panel is configured. Calls
without a signed-in user are refused for `set_pin`, `clear_pin`, `unlock` and
`status`. PIN rules: 4–8 digits, not one repeated digit and not a run of
consecutive digits (1234, 4321, 7890…), different from every other user's PIN.

Errors are raised as validation errors with a translation key
(`translation_domain: smartservice_alarm`), for example `wrong_pin`,
`locked_out` (placeholder `godzina`, local `HH:MM`), `pin_required`,
`mode_disabled`, `pin_taken`, `sensors_open` / `sensors_unavailable`
(placeholder `czujniki`). Home Assistant puts the English text into the error
message; a dashboard card that wants the user's language should translate the
key (`component.smartservice_alarm.exceptions.<key>.message`).

## Logbook and events

Every action fires `smartservice_alarm_event` with `akcja` (`uzbrojenie`,
`rozbrojenie`, `zly_kod`, `blokada`, `odblokowanie`, `wyzwolenie`,
`pin_ustawiony`, `pin_usuniety`), the mode, the PIN owner and the calling
account (ids and names), the sensor name, attempt counters and the lockout end.
The logbook shows it as text, for example *Disarmed: Anna (from account:
Living room tablet)* or *Wrong PIN from account Anna (3/5)*.

## Security model

- **No PIN is stored.** Each PIN is kept only as a scrypt hash
  (`n=2^14, r=8, p=1`, 32 bytes) with a random 16-byte salt per user, in the
  integration's private storage file `.storage/smartservice_alarm.<entry_id>`.
  The parameters are stored with every PIN, so they can be raised later
  without breaking existing PINs.
- **Constant work.** Every code check hashes the given code for every stored
  user and compares all results with `hmac.compare_digest`, so the time does
  not reveal whose PIN it is. Hashing runs in executor threads.
- **Lockout per calling account.** 5 wrong PINs in a row lock the account for
  60 s; each further lockout doubles (120, 240, 480 s) up to 15 minutes.
  During a lockout attempts are refused without hashing. A correct PIN does
  **not** clear the count of wrong PINs (otherwise a household member could
  keep guessing other PINs between uses of their own): the count is forgotten
  after 15 minutes without a wrong PIN, and the lockout length drops one step
  per day without a wrong PIN. Changing a PIN does not lift a lockout; an
  administrator can `unlock`. Calls without a user share the account `_bez_konta`. Lockouts
  survive a restart.
- **No PIN oracle.** For a normal user, a `set_pin` that collides with somebody
  else's PIN and a wrong `current_pin` both count as failed attempts.
- PINs and lockouts of deleted users are removed.
- Diagnostics redact salts and hashes; `status`, attributes, events and logs
  never contain a PIN, a hash or a salt.
- The *default code* of the alarm entity settings is ignored on purpose.

**Note about the recorder.** Home Assistant fires a `call_service` event for
every action call, with the call data — that includes the `code` of
`alarm_control_panel.*` and the `pin` of `set_pin`. The recorder stores these
events in its database by default (this applies to every alarm panel with a
code). PINs then stay in the database until the recorder purges old events
(`purge_keep_days`, 10 days by default); only somebody with access to the
Home Assistant files or database can read them. To keep PINs out of the
database, exclude the event type in your configuration (it only removes the
"triggered by action …" note from manual actions in the logbook):

```yaml
recorder:
  exclude:
    event_types:
      - call_service
```

## Performance

`tools/bench_scrypt.py` measures one full check for N users (default 8) with
the production parameters on the machine where it runs:

```bash
python3 tools/bench_scrypt.py --users 8
```

## License

MIT — see [LICENSE](LICENSE).
