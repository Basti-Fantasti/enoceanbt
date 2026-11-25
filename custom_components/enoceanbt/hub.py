"""Rocker hub: routes F6 telegrams from the dongle to event entities and teach flows."""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.helpers.dispatcher import async_dispatcher_send

from .rocker import RockerAction, RockerTracker, decode

_LOGGER = logging.getLogger(__name__)

_RORG_RPS = 0xF6
_DEFAULT_ACTOR_ID = [0xFF, 0xFF, 0xFF, 0xFF]


def signal_for(address: int) -> str:
    """Dispatcher signal carrying RockerEvents for one sender address."""
    return f"enoceanbt_rocker_{address:08X}"


def _combine(data) -> int:
    """Big-endian combination, identical to EnOceanDongle._combine_hex."""
    output = 0x00
    for i, j in enumerate(reversed(data)):
        output |= (j << i * 8)
    return output


class RockerHub:
    """Decodes rocker telegrams and fans them out. All methods run in the event loop."""

    def __init__(self, hass, dongle_getter: Callable[[], Any]) -> None:
        self._hass = hass
        self._dongle_getter = dongle_getter
        self._trackers: dict[int, RockerTracker] = {}
        self._teach_listeners: list[Callable[[int, RockerAction, float], None]] = []

    def handle_raw(self, sender: int, data1: int, status: int, t: float) -> None:
        """Handle one F6 telegram (called via loop.call_soon_threadsafe)."""
        action = decode(_RORG_RPS, data1, status)
        if action is None:
            return
        for listener in list(self._teach_listeners):
            try:
                listener(sender, action, t)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Teach listener failed")
        tracker = self._trackers.get(sender)
        if tracker is None:
            return
        for event in tracker.handle(action, t):
            async_dispatcher_send(self._hass, signal_for(sender), event)

    def register(self, address: int) -> None:
        """Start tracking a rocker address (one tracker per address)."""
        if address not in self._trackers:
            self._trackers[address] = RockerTracker()

    def unregister(self, address: int) -> None:
        """Stop tracking a rocker address."""
        self._trackers.pop(address, None)

    def add_teach_listener(
        self, cb: Callable[[int, RockerAction, float], None]
    ) -> Callable[[], None]:
        """Receive every decoded rocker action; returns a remove function."""
        self._teach_listeners.append(cb)

        def _remove() -> None:
            if cb in self._teach_listeners:
                self._teach_listeners.remove(cb)

        return _remove

    @property
    def connected(self) -> bool:
        """True if the dongle exists and its serial port is connected."""
        dongle = self._dongle_getter()
        return dongle is not None and dongle.connected

    def actor_users(self, address: int) -> list[str]:
        """Names of registered YAML devices whose actor_id equals the address."""
        dongle = self._dongle_getter()
        if dongle is None:
            return []
        names = []
        for device in dongle.devices:
            actor_id = getattr(device, "actor_id", None)
            if not actor_id or list(actor_id) == _DEFAULT_ACTOR_ID:
                continue
            if _combine(actor_id) == address:
                names.append(str(getattr(device, "name", "")))
        return names
