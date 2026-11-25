"""Event entities for taught EnOcean rocker switches."""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import DOMAIN
from .hub import signal_for
from .rocker import RockerEvent, key_for, keys_for_layout

EVENT_TYPES = ["press", "short_release", "long_release"]


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Create one event entity per rocker key of the entry's layout."""
    layout = entry.data["layout"]
    async_add_entities(
        EnOceanRockerEvent(entry, key) for key in keys_for_layout(layout)
    )


class EnOceanRockerEvent(EventEntity):
    """One rocker key (e.g. left_up) emitting press/release events."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry, key: str) -> None:
        self._address: int = entry.data["address"]
        self._mapping: dict = entry.data["mapping"]
        self._key = key
        layout = entry.data["layout"]
        self._attr_translation_key = key
        self._attr_unique_id = f"{self._address:08X}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._address:08X}")},
            name=entry.title,
            manufacturer="EnOcean",
            model=f"Wandtaster {layout} (F6-02)",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to the hub signal for this rocker's address."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_for(self._address), self._handle_event
            )
        )

    @callback
    def _handle_event(self, event: RockerEvent) -> None:
        if key_for(self._mapping, event.button) != self._key:
            return
        attrs = (
            {"duration": round(event.duration, 2)}
            if event.duration is not None
            else None
        )
        self._trigger_event(event.event_type, attrs)
        self.async_write_ha_state()
