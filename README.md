# EnOcean BT

Home-Assistant-Custom-Component für EnOcean über einen USB300-kompatiblen Stick
(Eltako-Aktoren, Wandtaster, Rollläden, Dimmer). Abgeleitet von der früheren
Core-Integration `enocean`.

## Installation

Manuell: `custom_components/enoceanbt` nach `/config/custom_components/` kopieren
(oder `deploy.ps1` aus dem USB/IP-Projekt verwenden) und HA neu starten.
HACS (Custom Repository) ist möglich, Updates werden aber bewusst manuell eingespielt.

## Konfiguration

```yaml
enoceanbt:
  device: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A60149N0-if00-port0
```

Immer den `/dev/serial/by-id/`-Pfad verwenden.

## Taster einlernen

Wandtaster (F6-02, Einfach- oder Doppelwippe) werden in der Oberfläche eingelernt;
der Stick selbst bleibt in der `configuration.yaml`.

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → EnOcean BT*.
2. Bauform wählen: `1x2` (Einfachwippe) oder `2x2` (Doppelwippe).
3. Wenn der Dialog es verlangt, die Taste **oben** (1x2) bzw. **links oben** (2x2)
   drücken und loslassen. Wurden mehrere Sender empfangen, den Taster aus der Liste
   wählen (Sender ohne Loslass-Telegramm sind als „vermutlich Aktor“ markiert).
4. Zur Bestätigung die Taste **unten** bzw. **rechts unten** drücken.
5. Name und optional Bereich vergeben.

Pro Taste entsteht eine Ereignis-Entität (z. B. `event.flur_links_oben`) mit den
Ereignistypen `press`, `short_release` und `long_release`.

Beispiel: Rollladen fahren, solange die Taste gedrückt ist:

```yaml
automation:
  - alias: Rollladen Flur hoch, solange gedrückt
    mode: restart
    triggers:
      - trigger: state
        entity_id: event.flur_links_oben
        not_from: unavailable
    actions:
      - choose:
          - conditions:
              - condition: state
                entity_id: event.flur_links_oben
                attribute: event_type
                state: press
            sequence:
              - action: cover.open_cover
                target:
                  entity_id: cover.rollladen_flur
          - conditions:
              - condition: state
                entity_id: event.flur_links_oben
                attribute: event_type
                state: long_release
            sequence:
              - action: cover.stop_cover
                target:
                  entity_id: cover.rollladen_flur
```

## Tests

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pytest
```
