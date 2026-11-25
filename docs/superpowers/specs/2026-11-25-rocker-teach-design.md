# EnOcean-Taster einlernen und als Auslöser nutzen – Design

Stand: 2026-11-25 · Repo: `Basti-Fantasti/enoceanbt` · Ziel-HA: 2026.11.3 (ha-teufel)

## Absicht

Vorhandene EnOcean-Wandtaster (PTM-Wippen, EEP F6-02-xx, 1x2 und 2x2), die an
**keinen** EnOcean-Aktor gebunden sind, sollen in Home Assistant als reine Auslöser
dienen: Tastendruck → beliebige Automation (z. B. Nicht-EnOcean-Rollladen hoch/runter,
Licht anderer Systeme). Heute geht das nur über `enoceanmqtt`, wo jede Adresse von Hand
in `enoceanmqtt.devices` eingetragen werden muss. Hier soll ein Einlern-Dialog in der
HA-Oberfläche das ersetzen: Dialog starten, Taster drücken, Taster bestätigen, fertig.

## Ziele

- Einlern-Dialog in der HA-UI („Integration hinzufügen → EnOcean BT“), der den
  nächsten gedrückten Taster erkennt und anzeigt.
- Pro Taster ein HA-Gerät mit Event-Entitäten je Taste, direkt als Trigger in
  Automationen nutzbar.
- Ereignisse: sofort beim Drücken, und beim Loslassen unterschieden in kurz/lang
  (Zeitmessung zwischen Drücken und Loslassen) – ermöglicht auch „fahren solange
  gedrückt“.
- Bestehende YAML-Covers und -Switches (virtuelle Sender, die an Eltako-Aktoren
  eingelernt sind, plus `actor_id`-Rückmeldungen) funktionieren unverändert.

## Nicht-Ziele (V1)

- Stick/Dongle auf UI-Konfiguration umstellen (bleibt `enoceanbt: device:` in YAML).
- Covers/Switches migrieren oder ändern.
- Alte `binary_sensor.py` reparieren (bleibt liegen, wird nicht genutzt).
- Gleichzeitiges Drücken zweier Tasten (Chords), Doppelklick.
- Import aus `enoceanmqtt.devices`.
- Senden als virtueller Taster.

## Anti-Ziele (wäre ein Fehlschlag, auch wenn es „läuft“)

- Ein Cover oder Switch reagiert nach dem Update anders als vorher.
- Ein Tasterdruck löst Aktor-Logik aus, die vorher nicht ausgelöst wurde (oder umgekehrt).
- Einlernen erfordert HA-Neustart oder Dateibearbeitung.
- Eltako-Aktoren (die auch F6-Telegramme senden) werden als Taster angelegt, ohne dass
  der Nutzer es merkt.

## Randbedingungen

- Integration nutzt `enocean==0.40`; Empfang läuft im Thread des `SerialCommunicator`
  (über `CommunicatorSupervisor`), Callback `EnOceanDongle.callback` in `__init__.py`.
  Alles, was HA-State berührt, muss thread-sicher in den Event-Loop übergeben werden.
- Dongle wird synchron in `setup()` aus YAML erzeugt (`ENOCEAN_DONGLE` global).
  Config-Entries kommen zusätzlich dazu; `setup()` bleibt.
- Die bestehende Telegramm-Auswertung in `callback` (wallswitch/actor/power/
  switch_status/dimmerstatus) wird **nicht verändert**. Die Taster-Erkennung läuft
  als zusätzlicher, unabhängiger Zweig.
- Tests: wie bisher HA-freie Module mit pytest (`tests/conftest.py` legt das
  Komponenten-Verzeichnis in `sys.path`). HA-abhängige Teile werden manuell auf
  ha-teufel getestet.
- Deployment: Kopie nach `\\192.168.10.1\config\custom_components\enoceanbt`, HA-Neustart.

## Ansätze (betrachtet)

| | Ansatz | Bewertung |
|---|---|---|
| **A** ✅ | **Pro Taster ein Config-Entry mit Einlern-Dialog; Dongle bleibt YAML** | Echte UI, keine Änderung an Bestehendem. Nachteil: zwei Konfigurationswege nebeneinander. **Gewählt vom Nutzer.** |
| B | Komplette Integration auf Config-Flow umbauen (Dongle + Taster) | Sauberer, aber muss YAML-Covers/Switches mitnehmen – Risiko für Bestehendes, für V1 unnötig. |
| C | Service `enoceanbt.teach`, Ergebnis als Notification | Taster müssten danach doch wieder händisch angelegt werden – halber Schritt. |

## Entscheidungen (mit Nutzer abgestimmt)

- Ansatz A.
- V1 braucht eindeutig zuordenbaren Tastendruck; kurz/lang mit Zeitmessung kommt mit
  in V1, weil der Aufwand gering ist.
- Taster sind an keine EnOcean-Aktoren gebunden; Covers/Switches dürfen nicht brechen.

## Design

### 1. Telegramm-Dekodierung (neues HA-freies Modul `rocker.py`)

F6-Telegramm (RPS), `data[0] == 0xF6`, Rocker-Byte `data[1]`, Status `data[6]`,
Sender `data[2..5]` (bzw. `packet.sender_int`):

- **Drücken:** Status hat NU-Bit (`0x10`) gesetzt (typisch `0x30`). `data[1]` Bits 7–5
  = R1 (0 = A-I, 1 = A-O, 2 = B-I, 3 = B-O), Bit 4 = Energiebügel gedrückt.
  Zweite Aktion (Bit 0 SA) wird in V1 ignoriert (= Chord, Nicht-Ziel).
- **Loslassen:** NU = 0 und `data[1] == 0x00` (typisch Status `0x20`). Telegramm sagt
  nicht, welche Taste – es gilt die zuletzt gedrückte Taste dieses Senders.
- NU = 0 mit `data[1] != 0x00` (Mehrfachtasten) → ignorieren.

Funktion etwa `decode(data: list[int], status: int) -> RockerAction | None`
mit `RockerAction(button: "AI"|"AO"|"BI"|"BO" | None, pressed: bool)`.

Zustandsmaschine pro Sender (`RockerTracker`, ebenfalls HA-frei, Zeitquelle injizierbar):

- `press(button, t)` → Ereignis `press` für `button`, merkt `button` + `t`.
- `release(t)` → wenn eine Taste gemerkt ist: Ereignis `short_release` (Dauer
  < `LONG_PRESS_S`) oder `long_release` (≥), mit `duration`; Merker löschen.
  Ohne Merker: nichts.
- Neues `press` ohne vorheriges Loslassen (verlorenes Release-Telegramm) → altes
  stillschweigend verwerfen, neues starten.
- Wiederholte Press-Telegramme derselben Taste (Repeater/Funk-Wiederholung) innerhalb
  von ~0,3 s ohne Release dazwischen → kein zweites `press`.
- `LONG_PRESS_S = 0.5` (Builder-Call, Konstante; später ggf. Option).

### 2. Anbindung im Callback

In `EnOceanDongle.callback`, **vor** der bestehenden Logik und ohne sie zu verändern:
wenn `RadioPacket` und `data[0] == 0xF6` → Rohdaten (Sender-int, `data[1]`, `data[6]`,
Empfangszeit `time.monotonic()`) per `hass.loop.call_soon_threadsafe` an einen
`RockerHub` im Event-Loop übergeben. Dafür braucht `EnOceanDongle` Zugriff auf `hass`
(wird schon übergeben, nur speichern).

`RockerHub` (in `hass.data[DOMAIN]`):
- hält registrierte Taster (Adresse → Tracker) und verteilt Ereignisse per
  `async_dispatcher_send(hass, f"{DOMAIN}_rocker_{addr:08X}", event)`.
- bietet „Mithören“ für den Einlern-Dialog: alle F6-**Drück**-Telegramme an einen
  temporären Listener weiterreichen.

### 3. Einlern-Dialog (Config-Flow, `config_flow.py`)

- `manifest.json`: `"config_flow": true`, Version `0.2.0`. Übersetzungen
  `strings.json` + `translations/de.json` + `translations/en.json`.
- Abbruch mit verständlicher Meldung, wenn der Dongle nicht läuft (kein YAML-Eintrag
  oder Stick getrennt).
Ablauf (vom Nutzer abgestimmt: Bauform vorab angeben, definierte Taste drücken,
zur Bestätigung erneut drücken):

1. **Schritt „layout“:** Bauform wählen: `1x2` (Einfachwippe, oben/unten) oder `2x2`
   (Doppelwippe, links/rechts je oben/unten).
2. **Schritt „listen_first“:** Progress-Schritt „Drücke jetzt **oben** (1x2) bzw.
   **links oben** (2x2) … (30 s)“. Hört bis zu 30 s mit; endet ~2 s nach dem ersten
   Kandidaten mit Druck **und** Loslassen, sonst nach Timeout → Fehlerseite mit „Nochmal“.
3. **Schritt „listen_second“:** „Drücke jetzt **unten** (1x2) bzw. **rechts unten**
   (2x2)“. Gewertet werden nur Telegramme desselben Senders (inkl. Loslassen).
   Prüfung: Die zweite Taste muss die Gegen-Taste sein (1x2: gleiche Wippe, andere
   Richtung; 2x2: andere Wippe **und** andere Richtung). Passt es nicht → Hinweis und
   Wiederholung. Damit ist der Taster doppelt bestätigt und die Zuordnung eindeutig.
4. **Zuordnung:** Aus den beiden gedrückten R1-Werten wird die Zuordnung abgeleitet
   und im Entry gespeichert: welche Wippe (A/B) = links/rechts bzw. die einzige Wippe
   bei 1x2, und welche Richtung (I/O) = oben/unten. Keine feste Tabelle im Code.
- **Filter:** ausgeschlossen werden
  - Adressen, die bereits als Taster-Entry existieren (zusätzlich `unique_id` = Adresse
    → doppelte Entries werden ohnehin abgebrochen),
  - Telegramme ohne NU-Bit (keine Tasten-Drücke).
  - **Kein** Ausschluss über `actor_id`: Die Covers „Rollladen Gast/Atelier“ nutzen als
    `actor_id` die echten Taster `0x0031D096` und `0x0031E02F` (vom Nutzer bestätigt).
    Ein `actor_id`-Filter würde genau diese Taster unlernbar machen. Stattdessen zeigt
    der Bestätigungsschritt einen Hinweis „wird bereits von Cover X ausgewertet“.
- **Aktor-Erkennung über Release (Design-Call):** Eltako-Aktor-Statustelegramme
  (`0x30`, `data[1]` = `0x70`/`0x50`) sehen aus wie ein Tastendruck, aber Aktoren
  senden nie ein Loslass-Telegramm. Das Mithören reicht daher Drück- **und**
  Loslass-Telegramme weiter. Ein Kandidat gilt als „Taster“, wenn auf seinen
  Druck ein Release folgt. Kandidaten ohne Release werden im Bestätigungsschritt
  als „vermutlich Aktor“ markiert und nie vorausgewählt. Vorausgewählt wird der
  zuletzt gedrückte Kandidat mit Release.
5. **Schritt „confirm“:** zeigt die erkannte Adresse (`0x0031E010`), ggf. den
   Cover-Hinweis und, falls im ersten Schritt mehrere Kandidaten kamen, eine
   Auswahlliste (siehe Aktor-Erkennung). Felder: Name (Pflicht), Bereich (optional,
   Area-Selector).
- Entry-Daten: `address` (int), `layout`, Zuordnung (z. B.
  `{"left": "A", "right": "B", "up": "I", "down": "O"}`; bei 1x2 nur Wippe + oben/unten).
  Titel = Name. `unique_id` = `f"{address:08X}"`.

Optionen-Flow (Bauform/Name ändern) ist **nicht** V1; umbenennen geht über HA-Geräteseite.

### 4. Gerät und Entitäten (`event.py`)

- `__init__.py` bekommt `async_setup_entry`/`async_unload_entry` (Plattform `event`),
  registriert die Adresse beim `RockerHub` und meldet sie beim Entladen ab.
- Ein Gerät pro Taster: Hersteller „EnOcean“, Modell „Wandtaster 1x2/2x2 (F6-02)“,
  Identifier `(DOMAIN, "0031E010")`, ggf. `suggested_area`.
- Event-Entität **pro Taste**:
  - 2x2 → 4 Entitäten, 1x2 → 2 Entitäten (nur die beim Einlernen gedrückte Wippe).
  - Namen: „Links oben/unten“, „Rechts oben/unten“ (1x2: „Oben/Unten“), aufgelöst über
    die im Entry gespeicherte Zuordnung. Telegramme der bei 1x2 nicht genutzten Wippe
    werden ignoriert.
  - `event_types = ["press", "short_release", "long_release"]`,
    Attribut `duration` bei Release-Ereignissen.
  - `device_class = EventDeviceClass.BUTTON`, `unique_id` = `f"{addr:08X}_{button}"`.
- Verfügbarkeit: unavailable, wenn der Supervisor „nicht verbunden“ meldet (optional;
  Builder-Call, ob in V1).

Beispiel-Automation (Rollladen fahren, solange gehalten):
`press` auf „Links oben“ → Cover öffnen; `long_release` auf „Links oben“ → Cover stoppen.
Einfacher Klick: Trigger `short_release` (oder `press`, wenn sofortige Reaktion wichtiger ist).

### 5. Tests

- Unit-Tests (pytest, HA-frei): `decode` für alle R1-Werte, Release, Mehrfachtasten,
  Nicht-F6; `RockerTracker` für kurz/lang, Grenze `LONG_PRESS_S`, verlorenes Release,
  wiederholtes Press, Release ohne Press.
- Bestehende Tests (`test_cover_logic`, `test_dongle_supervisor`) müssen weiter grün sein.
- Manuell auf ha-teufel:
  1. Nach Deploy: Covers „Rollladen Gast/Atelier“ und Licht-Switches wie vorher.
  2. Einlernen für mind. einen 2x2- und den 1x2-Taster (`rocker_flur_og`, `0x0031D020`).
  3. Zuordnung oben/unten links/rechts prüfen.
  4. kurz/lang, Event-Historie, Test-Automation.
  5. Taster `0x0031D096` einlernen: Cover-Hinweis erscheint, Cover „Rollladen Gast“
     verhält sich wie vorher.
  6. Stick ziehen/stecken während Einlern-Dialog → saubere Fehlermeldung.

### 6. Aufräumen der alten enoceanmqtt-Entitäten (eigener Schritt, nach Deploy)

`enoceanmqtt` wird nicht mehr genutzt. In HA existieren noch ~49 Entitäten
`binary_sensor.e2m_rocker_*` (Status `unknown`, über MQTT-Discovery angelegt, in keiner
Automation verwendet). Sie werden entfernt, **bevor** die Taster neu eingelernt
werden. Dazu gehört, die zurückbehaltenen (retained) Discovery-Topics im MQTT-Broker zu leeren,
sonst legt HA sie beim nächsten Neustart wieder an. Das löscht Daten und braucht deshalb vor
der Ausführung eine Bestätigung durch den Nutzer.

## Offene Punkte für den Builder

- Genaue Mechanik des Progress-Schritts im Config-Flow (HA `async_show_progress` mit
  Task) – Builder-Entscheidung.
- Ob Verfügbarkeit an den Supervisor-Status gekoppelt wird.
