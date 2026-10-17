# Smart Service Alarm

Integracja dodatkowa do Home Assistant, która dodaje centralę alarmu
(`alarm_control_panel`) z **osobnym PIN-em dla każdego użytkownika
Home Assistant**. Centrala wie, kto uzbroił i rozbroił, blokuje konto po
błędnych PIN-ach i zapisuje każdą czynność w dzienniku — nigdy sam PIN.

[English description — README.md](README.md)

- Darmowa, otwarta (MIT), działa samodzielnie.
- Konfiguracja tylko z interfejsu (bez YAML).
- Po polsku i po angielsku.

## Instalacja (HACS)

1. HACS → trzy kropki → **Niestandardowe repozytoria**.
2. Repozytorium: `https://github.com/SmartServicePL/smartservice-alarm`, typ **Integracja**.
3. Zainstaluj **Smart Service Alarm** i uruchom ponownie Home Assistant.
4. **Ustawienia → Urządzenia oraz usługi → Pomocnicy → Utwórz pomocnika →
   Smart Service Alarm** (albo **Dodaj integrację** i wyszukaj). Podaj nazwę,
   np. `Dom` — centrala to wtedy `alarm_control_panel.dom`.

Instalacja ręczna: skopiuj `custom_components/smartservice_alarm` do folderu
`custom_components` konfiguracji i uruchom ponownie.

## Centrala

| | |
|---|---|
| Stany | `disarmed`, `arming`, `armed_away`, `armed_home`, `armed_night`, `pending`, `triggered` |
| Format kodu | liczba |
| Rozbrojenie | zawsze PIN-em użytkownika (jeden wyjątek niżej) |
| Uzbrojenie | PIN opcjonalny, chyba że włączono „PIN wymagany do uzbrojenia”; podany PIN musi być poprawny |

Przebieg: uzbrojenie → `arming` (opóźnienie wyjścia) → uzbrojona.
Wyzwolenie w czasie uzbrojenia → `pending` (opóźnienie wejścia) →
`triggered` (czas trwania alarmu) → powrót do tego samego trybu uzbrojenia.
Wyzwolenie przy rozbrojonej centrali albo w czasie opóźnienia wyjścia jest
pomijane.

Dodatkowe atrybuty (żadnych danych PIN):

| Atrybut | Znaczenie |
|---|---|
| `changed_by` | imię właściciela PIN-u, użytkownika wywołującego albo `Automatyzacja` |
| `zmiana_przez` | `uzytkownik`, `automatyzacja` albo `wyzwolenie` |
| `uzbrojenie_przez_automat` | `true`, gdy bieżące uzbrojenie przyszło z wywołania bez użytkownika (automatyzacja) |
| `czujnik_wyzwalajacy` | nazwa czujnika przekazana do `smartservice_alarm.trigger` |
| `tryb` | tryb uzbrojenia obowiązujący albo właśnie włączany |
| `koniec_odliczania` | koniec trwającego opóźnienia wyjścia, wejścia albo alarmu (ISO) |

**Nocne rozbrojenie przez automat.** Wywołanie bez użytkownika
(automatyzacja) może rozbroić bez PIN-u tylko wtedy, gdy centrala jest w
stanie `armed_night`, to uzbrojenie zrobiła automatyzacja i od tego czasu nie
było `pending` ani `triggered`. Każde inne rozbrojenie bez PIN-u jest
odrzucane.

## Opcje

| Opcja | Domyślnie |
|---|---|
| Tryby: poza domem / w domu / noc | wszystkie włączone |
| Opóźnienie wyjścia | 60 s |
| Opóźnienie wejścia | 30 s |
| Czas trwania alarmu, potem powrót do uzbrojenia | 30 min |
| PIN wymagany do uzbrojenia | nie |
| Czujniki sprawdzane przy uzbrojeniu | brak |

Czujniki są sprawdzane przy **każdym** uzbrojeniu, także z automatyzacji.
Otwarty czujnik (`on`) — odmowa „Zamknij: <nazwy>”; czujnik `unavailable`,
`unknown` albo nieistniejący — odmowa „Brak odczytu: <nazwy>”. Bez
pomijania i wymuszania.

## Usługi

| Usługa | Pola | Kto |
|---|---|---|
| `smartservice_alarm.set_pin` | `user_id`, `pin`, `current_pin` (opcjonalnie), `entity_id` (opcjonalnie) | administrator każdemu; użytkownik tylko sobie, z `current_pin`, gdy już ma PIN |
| `smartservice_alarm.clear_pin` | `user_id`, `entity_id` (opcjonalnie) | administrator |
| `smartservice_alarm.unlock` | `user_id` (albo `_bez_konta`), `entity_id` (opcjonalnie) | administrator |
| `smartservice_alarm.status` | `entity_id` (opcjonalnie) | administrator; zwraca `{user_id: {"pin": bool, "zablokowany_do": ISO albo null}}` |
| `smartservice_alarm.trigger` | centrala, `czujnik` (opcjonalnie) | każdy (zwykle automatyzacja) |

`entity_id` jest potrzebne tylko przy więcej niż jednej centrali. Wywołania
bez zalogowanego użytkownika są odrzucane dla `set_pin`, `clear_pin`,
`unlock` i `status`. Reguły PIN-u: 4–8 cyfr, nie jedna powtórzona cyfra i
nie ciąg kolejnych cyfr (1234, 4321, 7890…), inny niż PIN każdego innego
użytkownika.

Błędy są zgłaszane jako błędy walidacji z kluczem tłumaczenia
(`translation_domain: smartservice_alarm`), np. `wrong_pin` („Błędny PIN.”),
`locked_out` („Zbyt wiele błędnych prób. Spróbuj o {godzina}.”, godzina
lokalna `HH:MM`), `pin_required` („Podaj PIN.”), `mode_disabled`,
`pin_taken`, `sensors_open` / `sensors_unavailable` (placeholder `czujniki`).
Home Assistant wpisuje do treści błędu tekst angielski; karta, która ma
pokazać komunikat po polsku, tłumaczy klucz
(`component.smartservice_alarm.exceptions.<klucz>.message`).

## Dziennik i zdarzenia

Każda czynność wysyła zdarzenie `smartservice_alarm_event` z polem `akcja`
(`uzbrojenie`, `rozbrojenie`, `zly_kod`, `blokada`, `odblokowanie`,
`wyzwolenie`, `pin_ustawiony`, `pin_usuniety`), trybem, właścicielem PIN-u i
kontem wywołującym (id i imiona), nazwą czujnika, licznikiem prób i końcem
blokady. Dziennik pokazuje je jako tekst, np. „Rozbrojenie: Zbigniew (z konta:
Tablet salon)”, „Błędny PIN z konta Zbigniew (3/5)”, „Blokada konta Zbigniew
do 18:05”, „Alarm: drzwi ogrodowe”.

## Model bezpieczeństwa

- **PIN nie jest zapisywany.** Każdy PIN istnieje tylko jako skrót scrypt
  (`n=2^14, r=8, p=1`, 32 bajty) z losową 16-bajtową solą na użytkownika, w
  prywatnym pliku integracji `.storage/smartservice_alarm.<entry_id>`.
  Parametry są zapisane przy każdym PIN-ie, więc można je później podnieść
  bez łamania istniejących PIN-ów.
- **Stała praca.** Każde sprawdzenie kodu liczy skrót dla każdego zapisanego
  użytkownika i porównuje wszystkie wyniki `hmac.compare_digest`, więc czas
  nie zdradza, czyj to PIN. Liczenie odbywa się w wątkach executora.
- **Blokada per konto wywołujące.** 5 błędnych PIN-ów z rzędu blokuje konto
  na 60 s; każda kolejna blokada się podwaja (120, 240, 480 s) do 15 minut.
  W blokadzie próby są odrzucane bez liczenia skrótu. Poprawny PIN zeruje
  konto; zmiana PIN-u nie zdejmuje blokady; administrator może użyć `unlock`.
  Wywołania bez użytkownika mają wspólne konto `_bez_konta`. Blokady
  przetrwają restart.
- **Bez wyroczni PIN-ów.** U zwykłego użytkownika `set_pin` z cudzym PIN-em
  i błędny `current_pin` liczą się jako nieudane próby.
- PIN-y i blokady usuniętych użytkowników są usuwane.
- Diagnostyka ukrywa sole i skróty; `status`, atrybuty, zdarzenia i logi nigdy
  nie zawierają PIN-u, skrótu ani soli.
- „Kod domyślny” z ustawień encji alarmu jest celowo pomijany.

**Uwaga o rejestratorze (recorder).** Home Assistant przy każdym wywołaniu
usługi wysyła zdarzenie `call_service` z danymi wywołania — także z `code`
usług `alarm_control_panel.*` i `pin` usługi `set_pin`. Rejestrator domyślnie
zapisuje te zdarzenia w bazie (dotyczy to każdej centrali z kodem). Żeby PIN-y
nie trafiały do bazy, wyklucz ten typ zdarzeń w konfiguracji:

```yaml
recorder:
  exclude:
    event_types:
      - call_service
```

## Wydajność

`tools/bench_scrypt.py` mierzy jedno pełne sprawdzenie dla N użytkowników
(domyślnie 8) z parametrami produkcyjnymi na maszynie, na której działa:

```bash
python3 tools/bench_scrypt.py --users 8
```

## Licencja

MIT — zobacz [LICENSE](LICENSE).
