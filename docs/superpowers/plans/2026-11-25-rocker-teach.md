# Taster-Einlernen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EnOcean-Wandtaster (F6-02, 1x2/2x2) per Einlern-Dialog in HA anlernen und als Event-Entitäten (press / short_release / long_release) für Automationen bereitstellen.

**Architecture:** Telegramm-Dekodierung, Kurz/Lang-Zustandsmaschine und Einlern-Logik liegen in HA-freien Modulen (`rocker.py`, `teach.py`) mit pytest-Tests. Ein `RockerHub` im HA-Event-Loop nimmt F6-Rohdaten aus dem Serial-Thread entgegen, verteilt Ereignisse per Dispatcher und bedient den Config-Flow. Pro Taster ein Config-Entry; Dongle, Covers und Switches bleiben unverändert in YAML.

**Tech Stack:** Python, Home Assistant 2026.11 (ConfigFlow mit `async_show_progress`, `EventEntity`), `enocean==0.40`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-rocker-teach-design.md`

## Global Constraints

- Bestehende Auswertung in `EnOceanDongle.callback` (wallswitch/actor/power/switch_status/dimmerstatus) wird **nicht verändert**; der Taster-Zweig kommt davor und ist unabhängig.
- `setup()` (YAML `enoceanbt: device:`) bleibt; `cover.py`, `switch.py`, `light.py`, `sensor.py`, `binary_sensor.py` werden nicht angefasst.
- Serial-Thread → Event-Loop nur über `hass.loop.call_soon_threadsafe`.
- `LONG_PRESS_S = 0.5`, Repeat-Unterdrückung `REPEAT_S = 0.3`, Einlern-Timeout `30 s`, Sammelfenster nach erstem Kandidaten mit Release `2 s`.
- Event-Typen exakt: `press`, `short_release`, `long_release`; Attribut `duration` (Sekunden, float) bei Release-Ereignissen.
- `unique_id` Entry = `f"{address:08X}"`, Entität = `f"{address:08X}_{key}"`; Keys: 2x2 `left_up`, `left_down`, `right_up`, `right_down`; 1x2 `up`, `down`.
- Kein Ausschluss über `actor_id` beim Einlernen; stattdessen Hinweis, welche Cover/Switches die Adresse schon als `actor_id` nutzen.
- `manifest.json`: `"config_flow": true`, `"version": "0.2.0"`.
- HA-freie Module dürfen nichts aus `homeassistant` importieren (Tests laufen ohne HA, Python 3.10 lokal).

## Review Focus

1. Eltako-Aktor-Status (`data[1]=0x70`, Status `0x30`, kein Release) während des Einlernens → erscheint höchstens als „vermutlich Aktor“, nie vorausgewählt. → Task 2, `test_actor_without_release_not_preselected`.
2. Verlorenes Release-Telegramm → nächster Druck startet neu, kein verspätetes `long_release` für die alte Taste. → Task 1, `test_lost_release_discards_old_press`.
3. Funk-Wiederholung desselben Druck-Telegramms (Repeater) → genau ein `press`. → Task 1, `test_repeated_press_within_repeat_window_fires_once`.
4. Zweiter Einlern-Schritt: Telegramme anderer Sender (Nachbartaster, Aktoren) werden ignoriert. → Task 2, `test_second_step_ignores_other_senders`.
5. Zweite Taste falsch (z. B. 2x2: gleiche Wippe gedrückt) → verständlicher Fehler statt falscher Zuordnung. → Task 1, `test_derive_mapping_2x2_rejects_same_channel`.

---

## Datei-Struktur

| Datei | Verantwortung |
|---|---|
| `custom_components/enoceanbt/rocker.py` (neu) | `decode`, `RockerTracker`, `derive_mapping`, `key_for`, `keys_for_layout` – HA-frei |
| `custom_components/enoceanbt/teach.py` (neu) | `TeachCollector` – Kandidaten sammeln, Release-Erkennung, Vorauswahl – HA-frei |
| `custom_components/enoceanbt/hub.py` (neu) | `RockerHub` – Loop-seitige Verteilung, Teach-Listener, Abfragen an den Dongle |
| `custom_components/enoceanbt/__init__.py` | Hub anlegen, F6-Weiterleitung im Callback, `async_setup_entry`/`async_unload_entry`, Dongle-Accessors |
| `custom_components/enoceanbt/config_flow.py` (neu) | Einlern-Dialog |
| `custom_components/enoceanbt/event.py` (neu) | Event-Entitäten |
| `custom_components/enoceanbt/strings.json`, `translations/de.json`, `translations/en.json` (neu) | Texte |
| `custom_components/enoceanbt/manifest.json` | `config_flow`, Version |
| `tests/test_rocker.py`, `tests/test_teach.py` (neu) | Unit-Tests |
| `README.md` | Abschnitt „Taster einlernen“ |

Test-Setup (einmalig, falls nicht vorhanden):
`python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-test.txt`
Testlauf: `.venv/Scripts/python -m pytest -q`

---

### Task 1: Dekodierung, Kurz/Lang-Tracker, Zuordnung (`rocker.py`)

**Files:**
- Create: `custom_components/enoceanbt/rocker.py`
- Test: `tests/test_rocker.py`

**Interfaces:**
- Produces:
  - `BUTTONS = ("AI", "AO", "BI", "BO")` (Index = R1-Wert 0..3)
  - `@dataclass(frozen=True) class RockerAction: button: str | None; pressed: bool`
  - `decode(rorg: int, data1: int, status: int) -> RockerAction | None`
  - `@dataclass(frozen=True) class RockerEvent: button: str; event_type: str; duration: float | None`
  - `class RockerTracker(long_press_s: float = 0.5, repeat_s: float = 0.3)` mit `handle(action: RockerAction, t: float) -> list[RockerEvent]`
  - `class MappingError(ValueError)` mit Attribut `reason: str` (`"same_button"`, `"wrong_pair"`)
  - `derive_mapping(layout: str, first: str, second: str) -> dict`
    - 2x2 → `{"layout": "2x2", "left": "A", "right": "B", "up": "I", "down": "O"}` (Werte aus den gedrückten Tasten)
    - 1x2 → `{"layout": "1x2", "channel": "A", "up": "I", "down": "O"}`
  - `keys_for_layout(layout: str) -> tuple[str, ...]` (`("left_up","left_down","right_up","right_down")` bzw. `("up","down")`)
  - `key_for(mapping: dict, button: str) -> str | None`

Dekodierregeln (aus Spec): `rorg != 0xF6` → `None`. NU = `status & 0x10`. NU gesetzt → `RockerAction(BUTTONS[data1 >> 5], True)` (SA-Bit 0 ignorieren). NU nicht gesetzt und `data1 == 0x00` → `RockerAction(None, False)`. Sonst `None`.
Tastenzerlegung: Wippe = `button[0]` (`"A"`/`"B"`), Richtung = `button[1]` (`"I"`/`"O"`). Erste Taste = oben (1x2) bzw. links oben (2x2), zweite = unten bzw. rechts unten.

- [ ] **Step 1: Failing tests schreiben** – `tests/test_rocker.py`:

```python
import pytest
from rocker import (decode, RockerAction, RockerTracker, RockerEvent,
                    derive_mapping, MappingError, key_for, keys_for_layout)

def test_decode_press_all_buttons():
    assert decode(0xF6, 0x10, 0x30) == RockerAction("AI", True)
    assert decode(0xF6, 0x30, 0x30) == RockerAction("AO", True)
    assert decode(0xF6, 0x50, 0x30) == RockerAction("BI", True)
    assert decode(0xF6, 0x70, 0x30) == RockerAction("BO", True)

def test_decode_release():
    assert decode(0xF6, 0x00, 0x20) == RockerAction(None, False)

def test_decode_multi_button_release_ignored():
    assert decode(0xF6, 0x15, 0x20) is None

def test_decode_non_rps_ignored():
    assert decode(0xA5, 0x10, 0x30) is None

def test_short_press():
    tr = RockerTracker()
    assert tr.handle(RockerAction("AI", True), 10.0) == [RockerEvent("AI", "press", None)]
    [ev] = tr.handle(RockerAction(None, False), 10.2)
    assert (ev.button, ev.event_type) == ("AI", "short_release")
    assert ev.duration == pytest.approx(0.2)

def test_long_press_boundary():
    tr = RockerTracker()
    tr.handle(RockerAction("BO", True), 0.0)
    [ev] = tr.handle(RockerAction(None, False), 0.5)
    assert ev.event_type == "long_release"

def test_release_without_press_is_ignored():
    assert RockerTracker().handle(RockerAction(None, False), 1.0) == []

def test_lost_release_discards_old_press():
    tr = RockerTracker()
    tr.handle(RockerAction("AI", True), 0.0)
    assert tr.handle(RockerAction("BI", True), 5.0) == [RockerEvent("BI", "press", None)]
    [ev] = tr.handle(RockerAction(None, False), 5.1)
    assert (ev.button, ev.event_type) == ("BI", "short_release")

def test_repeated_press_within_repeat_window_fires_once():
    tr = RockerTracker()
    tr.handle(RockerAction("AI", True), 0.0)
    assert tr.handle(RockerAction("AI", True), 0.1) == []

def test_derive_mapping_2x2():
    assert derive_mapping("2x2", "BO", "AI") == {"layout": "2x2", "left": "B", "right": "A", "up": "O", "down": "I"}

def test_derive_mapping_1x2():
    assert derive_mapping("1x2", "AI", "AO") == {"layout": "1x2", "channel": "A", "up": "I", "down": "O"}

def test_derive_mapping_2x2_rejects_same_channel():
    with pytest.raises(MappingError) as e: derive_mapping("2x2", "AI", "AO")
    assert e.value.reason == "wrong_pair"

def test_derive_mapping_rejects_same_button():
    with pytest.raises(MappingError) as e: derive_mapping("1x2", "AI", "AI")
    assert e.value.reason == "same_button"

def test_derive_mapping_1x2_rejects_other_channel():
    with pytest.raises(MappingError) as e: derive_mapping("1x2", "AI", "BO")
    assert e.value.reason == "wrong_pair"

def test_key_for():
    m = derive_mapping("2x2", "AI", "BO")
    assert [key_for(m, b) for b in ("AI", "AO", "BI", "BO")] == ["left_up", "left_down", "right_up", "right_down"]
    m1 = derive_mapping("1x2", "BI", "BO")
    assert key_for(m1, "AI") is None and key_for(m1, "BO") == "down"

def test_keys_for_layout():
    assert keys_for_layout("1x2") == ("up", "down")
```

- [ ] **Step 2:** `.venv/Scripts/python -m pytest tests/test_rocker.py -q` → FAIL (`ModuleNotFoundError: rocker`).
- [ ] **Step 3:** `rocker.py` gemäß Interfaces implementieren. Tracker merkt `(button, t_press)`; gleiches `button` als Press innerhalb `repeat_s` seit letztem Press-Telegramm ohne Release → `[]`; Press einer anderen Taste oder nach `repeat_s` ohne Release → alte verwerfen, neues `press`. Release: `duration = t - t_press`, `long_release` wenn `duration >= long_press_s`.
- [ ] **Step 4:** `.venv/Scripts/python -m pytest -q` → alle grün (inkl. bestehender Tests).
- [ ] **Step 5:** Commit `feat(rocker): F6-Dekodierung, Kurz/Lang-Tracker und Tastenzuordnung`.

---

### Task 2: Einlern-Sammler (`teach.py`)

**Files:**
- Create: `custom_components/enoceanbt/teach.py`
- Test: `tests/test_teach.py`

**Interfaces:**
- Consumes: `RockerAction` aus Task 1.
- Produces:
  - `@dataclass class Candidate: sender: int; button: str; released: bool; last_press: float; released_at: float | None`
  - `class TeachCollector(only_sender: int | None = None, settle_s: float = 2.0)`
    - `feed(sender: int, action: RockerAction, t: float) -> None` – Press legt/aktualisiert Kandidat (erste gedrückte Taste je Sender bleibt `button`, `last_press` aktualisiert); Release markiert den Kandidaten dieses Senders `released=True`, `released_at=t`, falls vorher ein Press kam. Bei `only_sender` werden andere Sender ignoriert.
    - `ready(t: float) -> bool` – es gibt einen Kandidaten mit Release und `t - released_at >= settle_s`.
    - `candidates() -> list[Candidate]` – sortiert: mit Release zuerst, dann `last_press` absteigend.
    - `preselect() -> Candidate | None` – erster Kandidat mit `released=True`, sonst `None`.

- [ ] **Step 1: Failing tests** – `tests/test_teach.py`:

```python
from rocker import RockerAction
from teach import TeachCollector

P = lambda b: RockerAction(b, True)
R = RockerAction(None, False)

def test_rocker_with_release_is_ready_after_settle():
    c = TeachCollector()
    c.feed(0x0031E010, P("AI"), 1.0); c.feed(0x0031E010, R, 1.1)
    assert not c.ready(2.0) and c.ready(3.1)
    assert c.preselect().sender == 0x0031E010 and c.preselect().button == "AI"

def test_actor_without_release_not_preselected():
    c = TeachCollector()
    c.feed(0x0031E010, P("AI"), 1.0); c.feed(0x0031E010, R, 1.1)
    c.feed(0x05127C55, P("BO"), 1.3)          # Eltako-Status, kein Release
    assert c.preselect().sender == 0x0031E010
    assert [x.released for x in c.candidates()] == [True, False]

def test_only_actor_seen_is_never_ready():
    c = TeachCollector()
    c.feed(0x05127C55, P("BO"), 1.0)
    assert not c.ready(10.0) and c.preselect() is None

def test_second_step_ignores_other_senders():
    c = TeachCollector(only_sender=0x0031E010, settle_s=0.0)
    c.feed(0x0031D020, P("AO"), 1.0); c.feed(0x0031D020, R, 1.1)
    assert not c.ready(1.2)
    c.feed(0x0031E010, P("BO"), 1.5); c.feed(0x0031E010, R, 1.6)
    assert c.ready(1.6) and c.preselect().button == "BO"

def test_release_before_any_press_ignored():
    c = TeachCollector()
    c.feed(0x0031E010, R, 1.0)
    assert c.candidates() == []
```

- [ ] **Step 2:** `pytest tests/test_teach.py -q` → FAIL.
- [ ] **Step 3:** `teach.py` gemäß Interfaces.
- [ ] **Step 4:** `.venv/Scripts/python -m pytest -q` → grün.
- [ ] **Step 5:** Commit `feat(teach): Kandidaten-Sammler mit Release-Erkennung`.

---

### Task 3: Hub und Anbindung an den Dongle (`hub.py`, `__init__.py`, Event-Plattform, Manifest)

Kein pytest (HA-abhängig); Prüfung per `py_compile` und im Deploy-Task. Plattform und Config-Flow kommen in Task 4, der Hub aber hier, damit Task 4 nur noch konsumiert.

**Files:**
- Create: `custom_components/enoceanbt/hub.py`, `custom_components/enoceanbt/event.py`
- Modify: `custom_components/enoceanbt/__init__.py`, `custom_components/enoceanbt/manifest.json`

**Interfaces:**
- Consumes: `decode`, `RockerTracker`, `RockerEvent`, `key_for`, `keys_for_layout` (Task 1).
- Produces:
  - `hub.py`:
    - `signal_for(address: int) -> str` → `f"enoceanbt_rocker_{address:08X}"`
    - `class RockerHub(hass)`:
      - `handle_raw(sender: int, data1: int, status: int, t: float) -> None` (läuft im Loop; dekodiert, schickt bei registrierter Adresse jedes `RockerEvent` per `async_dispatcher_send(hass, signal_for(sender), event)`; reicht `(sender, action, t)` an alle Teach-Listener)
      - `register(address: int) -> None` / `unregister(address: int) -> None` (je Adresse ein `RockerTracker`)
      - `add_teach_listener(cb: Callable[[int, RockerAction, float], None]) -> Callable[[], None]` (gibt Remove-Funktion zurück)
      - `connected -> bool` (Property; `ENOCEAN_DONGLE is not None and ENOCEAN_DONGLE.connected`)
      - `actor_users(address: int) -> list[str]` (Namen aller registrierten `EnOceanDevice` mit `actor_id`, deren kombinierter Wert == `address`)
  - `__init__.py`:
    - `EnOceanDongle.__init__` speichert `hass`; neue Properties `devices` (Liste) und `connected` (`self.__supervisor.state == "connected"`).
    - In `setup()`: `hass.data[DOMAIN] = {"hub": RockerHub(hass)}` **vor** Erzeugen des Dongles.
    - In `callback`, ganz am Anfang innerhalb `isinstance(temp, RadioPacket)`: wenn `temp.data[0] == 0xF6` → `self._hass.loop.call_soon_threadsafe(hub.handle_raw, temp.sender_int, temp.data[1], temp.data[6], time.monotonic())`. Restliche Logik unverändert darunter.
    - `async_setup_entry(hass, entry)`: wenn `DOMAIN not in hass.data` → `ConfigEntryNotReady`; `hub.register(entry.data["address"])`; Plattform `Platform.EVENT` forwarden; wenn `entry.data.get("area_id")` und Gerät hat keine Area → per Device-Registry setzen. `async_unload_entry`: Plattform entladen, `hub.unregister`.
  - `event.py`: `async_setup_entry` legt pro `keys_for_layout(entry.data["layout"])` eine `EnOceanRockerEvent` an.
    - `_attr_has_entity_name = True`, `translation_key = key`, `device_class = EventDeviceClass.BUTTON`, `event_types = ["press", "short_release", "long_release"]`, `unique_id = f"{address:08X}_{key}"`.
    - `DeviceInfo(identifiers={(DOMAIN, f"{address:08X}")}, name=entry.title, manufacturer="EnOcean", model=f"Wandtaster {layout} (F6-02)")`.
    - Abonniert `signal_for(address)`; nur wenn `key_for(mapping, event.button) == self._key`: `_trigger_event(event.event_type, {"duration": round(event.duration, 2)} if event.duration is not None else None)` + `async_write_ha_state()`.
  - `manifest.json`: `"config_flow": true`, `"version": "0.2.0"`.

- [ ] **Step 1:** `hub.py`, `event.py` und Änderungen in `__init__.py`/`manifest.json` umsetzen.
- [ ] **Step 2:** `git diff custom_components/enoceanbt/__init__.py` prüfen: bestehende `if/elif`-Kette und `for device in self.__devices`-Schleife sind Zeile für Zeile unverändert.
- [ ] **Step 3:** `.venv/Scripts/python -m py_compile custom_components/enoceanbt/hub.py custom_components/enoceanbt/event.py custom_components/enoceanbt/__init__.py` → keine Ausgabe; `.venv/Scripts/python -m pytest -q` → grün.
- [ ] **Step 4:** Commit `feat(hub): Taster-Telegramme an HA weiterreichen, Event-Entitaeten`.

---

### Task 4: Einlern-Dialog (`config_flow.py`, Texte)

**Files:**
- Create: `custom_components/enoceanbt/config_flow.py`, `strings.json`, `translations/de.json`, `translations/en.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: `RockerHub.add_teach_listener`, `.connected`, `.actor_users` (Task 3); `TeachCollector` (Task 2); `derive_mapping`, `MappingError` (Task 1).
- Produces: Config-Entry mit `data = {"address": int, "layout": "1x2"|"2x2", "mapping": dict, "area_id": str | None}`, `title = name`, `unique_id = f"{address:08X}"`.

Ablauf `EnOceanBtConfigFlow(ConfigFlow, domain=DOMAIN)`, `VERSION = 1`:

| Step | Inhalt |
|---|---|
| `user` | Abbruch `not_connected`, wenn Hub fehlt oder `not hub.connected`. Formular: `layout` (Select `1x2`/`2x2`, Default `2x2`). |
| `listen_first` | `async_show_progress(progress_action="press_first", progress_task=…)`; Task: Listener → `TeachCollector()`, alle 0,2 s `ready()` prüfen, max. 30 s. Danach `async_show_progress_done(next_step_id="pick" oder "timeout")`. |
| `timeout` | Formular ohne Felder, Text „Kein Taster erkannt“; Absenden → zurück zu `listen_first`. |
| `pick` | Nur wenn `len(candidates()) > 1`: Select über Kandidaten, Label `0x0031E010 (Taster)` bzw. `… (vermutlich Aktor)`, Default = `preselect()`. Sonst direkt weiter. Dann `async_set_unique_id(f"{addr:08X}")` + `_abort_if_unique_id_configured()`. |
| `listen_second` | wie `listen_first`, aber `TeachCollector(only_sender=addr, settle_s=0)`, Text „Drücke jetzt unten / rechts unten“. `derive_mapping` → bei `MappingError` Formular `wrong_second` mit Fehler `same_button`/`wrong_pair` und Wiederholung von `listen_second`. |
| `confirm` | Beschreibung zeigt Adresse und, falls `actor_users(addr)` nicht leer, „Wird bereits ausgewertet von: …“. Felder `name` (Pflicht), `area_id` (AreaSelector, optional). → `async_create_entry`. |

Texte (de, exakt sinngemäß; en analog):
- `press_first`: 1x2 „Drücke jetzt die Taste **oben**.“ / 2x2 „Drücke jetzt die Taste **links oben**.“ (Platzhalter `{target}` in der Beschreibung)
- `press_second`: „Drücke jetzt die Taste **unten**.“ / „Drücke jetzt die Taste **rechts unten**.“
- `abort.not_connected`: „Der EnOcean-Stick ist nicht verbunden oder `enoceanbt` ist nicht in der configuration.yaml eingerichtet.“
- `abort.already_configured`: „Dieser Taster ist bereits eingelernt.“
- `error.same_button`: „Das war dieselbe Taste wie eben – bitte die gegenüberliegende drücken.“
- `error.wrong_pair`: „Das war nicht die gegenüberliegende Taste – bitte erneut drücken.“
- Entitätsnamen (`entity.event.<key>.name`): `left_up` „Links oben“, `left_down` „Links unten“, `right_up` „Rechts oben“, `right_down` „Rechts unten“, `up` „Oben“, `down` „Unten“; State-Attribute `event_type`: „Gedrückt“, „Kurz losgelassen“, „Lang losgelassen“.

- [ ] **Step 1:** `config_flow.py` und die drei Textdateien umsetzen (`strings.json` = englisch, `translations/en.json` = Kopie, `translations/de.json` = deutsch).
- [ ] **Step 2:** `python -c "import json,sys;[json.load(open(f,encoding='utf-8')) for f in sys.argv[1:]]" custom_components/enoceanbt/strings.json custom_components/enoceanbt/translations/de.json custom_components/enoceanbt/translations/en.json` → keine Ausgabe; `py_compile config_flow.py` → keine Ausgabe; `pytest -q` → grün.
- [ ] **Step 3:** README: Abschnitt „Taster einlernen“ (Integration hinzufügen → EnOcean BT → Bauform → oben/links oben, dann unten/rechts unten drücken → Name/Bereich) + Beispiel-Automation „solange gedrückt fahren“ (`press` → `cover.open_cover`, `long_release` → `cover.stop_cover`).
- [ ] **Step 4:** Commit `feat(config_flow): Einlern-Dialog fuer Wandtaster`.

---

### Task 5: Deploy und Abnahme auf ha-teufel

**Files:** keine Code-Änderung (Fixes aus der Abnahme als eigene Commits).

- [ ] **Step 1:** Backup des installierten Stands: `\\192.168.10.1\config\custom_components\enoceanbt` nach `\\192.168.10.1\config\custom_components\enoceanbt_v3.7z` (wie bestehende `_v0..v2`) bzw. als Ordnerkopie in den Scratchpad.
- [ ] **Step 2:** `custom_components/enoceanbt/` (ohne `__pycache__`) auf die Freigabe kopieren.
- [ ] **Step 3:** **Nutzer fragen**, dann HA neu starten (`ha_restart`). Danach `ha_get_logs` auf `enoceanbt`-Fehler prüfen → keine Tracebacks.
- [ ] **Step 4:** Regression (Nutzer + Log): Rollladen Gast/Atelier und ein Licht-Switch schalten wie vorher.
- [ ] **Step 5:** Mit Nutzer einlernen und prüfen (Checkliste aus der Spec, Abschnitt Tests):
  1. 2x2 `0x0031E010` (Büro OG) einlernen → 4 Entitäten, Namen stimmen mit physischer Lage überein.
  2. 1x2 `0x0031D020` (Flur OG) einlernen → 2 Entitäten.
  3. Kurz/lang drücken → `event_type` und `duration` in der Entitäts-Historie.
  4. `0x0031D096` einlernen → Hinweis „Rollladen Gast“ im Bestätigungsschritt; Cover verhält sich wie vorher.
  5. Gleichen Taster nochmal einlernen → Abbruch `already_configured`.
  6. Falsche zweite Taste → Fehlertext, Wiederholung klappt.
- [ ] **Step 6:** Version-Tag `v0.2.0`, Push nach `origin/main` **nach Freigabe durch den Nutzer**.

---

### Task 6: Alte enoceanmqtt-Entitäten entfernen (nur mit Nutzerfreigabe)

- [ ] **Step 1:** Mit `ha_search(query="e2m_")` alle Entitäten listen und dem Nutzer zeigen; prüfen, dass keine Automation/Script/Dashboard sie referenziert.
- [ ] **Step 2:** **Freigabe einholen.**
- [ ] **Step 3:** Für jedes zugehörige Discovery-Topic `homeassistant/<domain>/<object_id>/config` per `mqtt.publish` (leerer Payload, `retain: true`) den Retained-Eintrag löschen; Topics aus dem MQTT-Geräte-Info bzw. `mqtt` Diagnostics ermitteln.
- [ ] **Step 4:** Verbliebene Geräte/Entitäten per `ha_remove_device`/`ha_remove_entity` entfernen; nach HA-Neustart erneut `ha_search("e2m_")` → 0 Treffer.

---

## Offen (nicht blockierend)

- Covers „Rollladen Gast/Atelier“ haben als `actor_id` echte Taster (`0x0031D096`, `0x0031E02F`). Ob dort die echte Aktor-Adresse eingetragen werden soll, entscheidet der Nutzer separat; dieser Plan ändert die Covers nicht.
