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

## Tests

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pytest
```
