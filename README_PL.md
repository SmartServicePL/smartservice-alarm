# Smart Service Alarm

Integracja dodatkowa do Home Assistant, która dodaje centralę alarmu
(`alarm_control_panel`) z **osobnym PIN-em dla każdego użytkownika
Home Assistant**. Centrala wie, kto uzbroił i rozbroił, blokuje konto po
błędnych PIN-ach i zapisuje każdą czynność w dzienniku — nigdy sam PIN.

[English description — README.md](README.md)

> Smart Service Alarm jest projektowany według zasad PN-EN 50131 (stopień 2), ale nie jest certyfikowaną centralą alarmową. Nie zastępuje profesjonalnego systemu alarmowego ani monitoringu agencji ochrony.

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

**Same PIN-y.** Wybierz rodzaj *Same PIN-y (bez centrali)*, gdy w domu nie ma
alarmu tej integracji, a widok w panelu (np. kamery) ma i tak pytać o osobny
PIN: wpis przechowuje PIN-y i blokady użytkowników i odpowiada na
`smartservice_alarm/check_pin`, a uzbrajać nie ma czego. To jedyne miejsce na
PIN-y: obok niego nie da się dodać drugiego wpisu (ani takiego wpisu obok
centrali, która sama przechowuje PIN-y). Żeby później mieć centralę, otwórz
opcje wpisu i ją włącz — PIN-y zostaną.

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

**Jedna czujka najwyżej 3 alarmy.** W jednym uzbrojeniu jedna czujka (nazwa
przekazana do `smartservice_alarm.trigger`) wyzwala alarm najwyżej 3 razy.
Kolejne jej wyzwolenia są pomijane do rozbrojenia: pierwsze z nich wysyła raz
`czujka_pominieta`, a czujka trafia do `czujniki_pominiete`. Inne czujki
wyzwalają dalej. Rozbrojenie i nowe uzbrojenie zerują licznik.

**Przerwa.** Gdy Home Assistant startuje ponownie, a centrala pilnowała
(opóźnienie wyjścia, uzbrojenie, opóźnienie wejścia albo alarm), odliczania
zakończone w czasie przerwy są nadrabiane, a po starcie Home Assistant
centrala wysyła `powrot_po_przerwie` z długością przerwy w minutach
(`przerwa_min`; bez tego pola, gdy nie wiadomo). Gdy pilnuje, centrala co
minutę i przy zatrzymaniu Home Assistant zapisuje chwilę, w której ostatnio
działała. Ponowne wczytanie wpisu nie jest przerwą.

Dodatkowe atrybuty (żadnych danych PIN):

| Atrybut | Znaczenie |
|---|---|
| `changed_by` | imię właściciela PIN-u, użytkownika wywołującego albo `Automatyzacja` |
| `zmiana_przez` | `uzytkownik`, `automatyzacja` albo `wyzwolenie` |
| `uzbrojenie_przez_automat` | `true`, gdy bieżące uzbrojenie przyszło z wywołania bez użytkownika (automatyzacja) |
| `czujnik_wyzwalajacy` | nazwa czujnika przekazana do `smartservice_alarm.trigger` |
| `tryb` | tryb uzbrojenia obowiązujący albo właśnie włączany |
| `koniec_odliczania` | koniec trwającego opóźnienia wyjścia, wejścia albo alarmu (ISO) |
| `czujniki_pominiete` | czujki pominięte do rozbrojenia po 3 alarmach (nazwy) |

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
| Czas trwania alarmu, potem powrót do uzbrojenia | 10 min |
| PIN wymagany do uzbrojenia | nie |
| Czujniki sprawdzane przy uzbrojeniu | brak |

Czujniki są sprawdzane przy **każdym** uzbrojeniu, także z automatyzacji.
Otwarty czujnik (`on`) — odmowa „Zamknij: <nazwy>”; czujnik `unavailable`,
`unknown` albo nieistniejący — odmowa „Brak odczytu: <nazwy>”. Bez
pomijania i wymuszania.

## Usługi

| Usługa | Pola | Kto |
|---|---|---|
| `smartservice_alarm.set_pin` | `user_id`, `pin`, `current_pin` (opcjonalnie), `entity_id` (opcjonalnie) | administrator każdemu; użytkownik tylko zmienia swój istniejący PIN, z `current_pin` (pierwszy PIN ustawia administrator) |
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

### Sprawdzenie PIN-u dla widoku w panelu (websocket)

Karta w panelu może chronić widok (np. „Bezpieczeństwo”) PIN-em alarmu przez
polecenie websocket `smartservice_alarm/check_pin`:

```js
await hass.callWS({ type: "smartservice_alarm/check_pin", pin: "2580" });
```

| Odpowiedź | Znaczenie |
|---|---|
| `{"wynik": "poprawny", "user_id": "…", "osoba": "Piotr"}` | PIN tego użytkownika |
| `{"wynik": "niepoprawny", "pozostalo": 3}` | błędny PIN; ile prób zostało do blokady |
| `{"wynik": "zablokowany", "do": "ISO"}` | konto albo cała centrala zablokowane do tej chwili |
| `{"wynik": "brak_pinow"}` | nikt nie ma jeszcze PIN-u; próba się nie liczy (najpierw ustaw PIN-y) |

`entity_id` jest opcjonalne, jak w usługach (błędy `unknown_alarm`,
`choose_alarm`). Może je wywołać każdy zalogowany użytkownik. Błędne PIN-y
liczą się razem z uzbrajaniem i rozbrajaniem: te same blokady, w obie strony.
Niczego więcej nie zmienia (ani stanu, ani atrybutów) i nigdy nie odpowiada
PIN-em. To celowo polecenie websocket, a nie usługa: dane wywołania usługi
trafiają do zdarzenia `call_service`, a więc do bazy recordera (patrz uwaga
niżej), dane polecenia websocket — nie.

## Dziennik i zdarzenia

Każda czynność wysyła zdarzenie `smartservice_alarm_event` z polem `akcja`
(`uzbrojenie`, `rozbrojenie`, `zly_kod`, `blokada`, `odblokowanie`,
`wyzwolenie`, `pin_ustawiony`, `pin_usuniety`, `odmowa_uzbrojenia` — otwarty
czujnik na końcu czasu na wyjście, `ustawienia` — zmiana ustawień centrali,
`czujka_pominieta` — czujka pominięta po 3 alarmach, `powrot_po_przerwie` —
Home Assistant wrócił po przerwie, gdy centrala pilnowała,
`wejscie_bezpieczenstwo` / `wejscie_bezpieczenstwo_nieudane` — sprawdzenie
PIN-u widoku w panelu, poprawne / błędne),
trybem, właścicielem PIN-u i kontem wywołującym (id i imiona), nazwą czujnika,
licznikiem prób i końcem blokady. Dziennik pokazuje je jako tekst, np. „Rozbrojenie: Jan (z konta:
Tablet salon)”, „Błędny PIN z konta Jan (3/5)”, „Blokada konta Jan
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
  W blokadzie próby są odrzucane bez liczenia skrótu. Poprawny PIN **nie**
  zeruje licznika błędnych prób (inaczej domownik mógłby zgadywać cudze PIN-y
  między użyciami własnego): licznik wygasa po 15 minutach bez błędnego PIN-u,
  a długość kolejnej blokady spada o jeden stopień po każdej dobie bez
  błędnego PIN-u. Zmiana PIN-u nie zdejmuje blokady; administrator może użyć
  `unlock`.
  Wywołania bez użytkownika mają wspólne konto `_bez_konta`. Blokady
  przetrwają restart.
- **Bez wyroczni PIN-ów.** U zwykłego użytkownika `set_pin` z cudzym PIN-em
  i błędny `current_pin` liczą się jako nieudane próby.
- **Pierwszy PIN ustawia administrator.** Każdy PIN rozbraja centralę, więc
  konto nie może nadać go samo sobie (konto dziecka, telewizora ani konto
  tylko do odczytu): zwykły użytkownik bez PIN-u dostaje odmowę `set_pin`
  (`first_pin_by_admin`).
- PIN-y i blokady usuniętych użytkowników są usuwane.
- Diagnostyka ukrywa sole i skróty; `status`, atrybuty, zdarzenia i logi nigdy
  nie zawierają PIN-u, skrótu ani soli.
- „Kod domyślny” z ustawień encji alarmu jest celowo pomijany.
- Sprawdzenie PIN-u dla widoku w panelu (`smartservice_alarm/check_pin`) to
  polecenie websocket, więc jego PIN nigdy nie trafia do zdarzenia
  `call_service` ani do bazy recordera. Tylko własny log debugowania API
  websocket w Home Assistant (`homeassistant.components.websocket_api`,
  domyślnie wyłączony) zapisuje każdą odebraną wiadomość — także ten PIN, tak
  jak tokeny dostępu; na co dzień zostaw go wyłączony.

### Uzbrajanie, rozbrajanie i PIN-y bez rejestratora (websocket)

Wszystko, co niesie PIN, ma też polecenie websocket. Karta w panelu albo
dodatek powinny używać ich zamiast usług:

| Polecenie | Pola | To samo co |
|---|---|---|
| `smartservice_alarm/arm` | `tryb` (`away`, `home`, `night`), `code` | `alarm_control_panel.alarm_arm_*` |
| `smartservice_alarm/disarm` | `code` | `alarm_control_panel.alarm_disarm` |
| `smartservice_alarm/set_pin` | `user_id`, `pin`, `current_pin` (opcjonalnie) | `smartservice_alarm.set_pin` |
| `smartservice_alarm/clear_pin` | `user_id` | `smartservice_alarm.clear_pin` |

Każde przyjmuje opcjonalne `entity_id`. Odpowiedź to `{"wynik": "ok"}`
(`clear_pin` dodaje `"usuniety": true/false`) albo ten sam błąd co w usłudze:
`code` i `translation_key` błędu websocket to klucz tłumaczenia (np.
`wrong_pin`, `locked_out` z `godzina`, `sensors_open` z `czujniki`,
`code_arm_required` z `alarm_control_panel`), a brak uprawnienia do sterowania
centralą to `unauthorized`. Polecenia wywołują te same metody centrali co
usługi, z kontekstem zalogowanego użytkownika, więc reguły, liczniki, blokady,
zdarzenia i dziennik są te same. Pole, które nie jest tekstem (ani liczbą),
nie jest odrzucane przez schemat (Home Assistant zapisałby je w logu); jest po
prostu brakiem PIN-u.

**Uwaga o rejestratorze (recorder).** Home Assistant przy każdym wywołaniu
usługi wysyła zdarzenie `call_service` z danymi wywołania — także z `code`
usług `alarm_control_panel.*` i `pin` usługi `set_pin`. Rejestrator domyślnie
zapisuje te zdarzenia w bazie (dotyczy to każdej centrali z kodem). PIN-y leżą
wtedy w bazie do czasu usunięcia starych zdarzeń (`purge_keep_days`, domyślnie
10 dni); odczyta je tylko ktoś z dostępem do plików albo bazy Home Assistant.
Polecenia websocket opisane wyżej nie zostawiają PIN-ów w bazie; żeby nie
zostawiały ich też usługi, wyklucz ten typ zdarzeń w konfiguracji (w
dzienniku znika wtedy tylko dopisek „wywołane akcją …” przy ręcznych akcjach):

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
