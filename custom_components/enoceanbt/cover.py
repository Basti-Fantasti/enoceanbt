"""Support for EnOcean covers (Eltako FSB61 roller shutters).

Each cover drives a time-based Eltako FSB61NP actuator that was taught a
virtual rocker (BaseID + offset, up/down channels), exactly like the switch
platform. The actuator has no absolute position; open/close/stop are rocker
taps and the cover state is tracked optimistically over the configured
travel_time, corrected by the actuator's RPS confirmation telegrams.
"""

import logging
import threading
import time

import voluptuous as vol

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    PLATFORM_SCHEMA,
)
from homeassistant.const import CONF_NAME, CONF_ID, CONF_DEVICE_CLASS
from custom_components import enoceanbt
from custom_components.enoceanbt.cover_logic import ShutterState
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'EnOceanBt Cover'
CONF_CHANNEL_UP = 'channel_up'
CONF_CHANNEL_DOWN = 'channel_down'
CONF_ACT_ID = 'actor_id'
CONF_TRAVEL_TIME = 'travel_time'
CONF_BASE_ID_OFFSET = 'base_id_offset'

CONST_SHORT_PRESS = 0.3

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_CHANNEL_UP, default=0): cv.positive_int,
    vol.Optional(CONF_CHANNEL_DOWN, default=1): cv.positive_int,
    vol.Optional(CONF_ACT_ID, default=[0xff, 0xff, 0xff, 0xff]):
        vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_TRAVEL_TIME, default=20): cv.positive_int,
    vol.Optional(CONF_BASE_ID_OFFSET, default=0): cv.positive_int,
    vol.Optional(CONF_DEVICE_CLASS, default='shutter'): cv.string,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the EnOcean cover platform."""
    dev_id = config.get(CONF_ID)
    devname = config.get(CONF_NAME)
    channel_up = config.get(CONF_CHANNEL_UP)
    channel_down = config.get(CONF_CHANNEL_DOWN)
    actor_id = config.get(CONF_ACT_ID)
    travel_time = config.get(CONF_TRAVEL_TIME)
    b_id_offset = config.get(CONF_BASE_ID_OFFSET)
    device_class = config.get(CONF_DEVICE_CLASS)

    add_entities([EnOceanCover(dev_id, b_id_offset, actor_id, devname,
                               channel_up, channel_down, travel_time,
                               device_class)])


class EnOceanCover(enoceanbt.EnOceanDevice, CoverEntity):
    """Representation of an EnOcean (Eltako FSB61) roller shutter."""

    def __init__(self, dev_id, b_id_offset, actor_id, devname,
                 channel_up, channel_down, travel_time, device_class):
        """Initialize the EnOcean cover device."""
        enoceanbt.EnOceanDevice.__init__(self)
        self.dev_id = dev_id
        self.dev_id[3] = self.dev_id[3] + b_id_offset
        self.actor_id = actor_id
        self.broadcast_id = [0xff, 0xff, 0xff, 0xff]
        self._devname = devname
        self.channel_up = channel_up
        self.channel_down = channel_down
        self._travel_time = travel_time
        self._device_class = device_class
        self.stype = "cover"
        self._state = ShutterState()
        self._timer = None

    @property
    def name(self):
        """Return the device name."""
        return self._devname

    @property
    def device_class(self):
        """Return the device class (e.g. shutter)."""
        return self._device_class

    @property
    def supported_features(self):
        """Flag supported features."""
        return (CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP)

    @property
    def is_closed(self):
        """Return True if closed, False if open, None if unknown."""
        return self._state.is_closed

    @property
    def is_opening(self):
        """Return True if the cover is currently opening."""
        return self._state.is_opening

    @property
    def is_closing(self):
        """Return True if the cover is currently closing."""
        return self._state.is_closing

    @property
    def assumed_state(self):
        """State is optimistic: time-based actuator, no position feedback.

        Tells the frontend to render open/close/stop as always-active
        momentary buttons instead of disabling them during travel.
        """
        return True

    def _send_tap(self, channel):
        """Send a single short RPS rocker tap on the given channel.

        Emits a complete PTM rocker short-press: the button-press telegram
        (data[1] = chan_high, status 0x30) followed by a proper release
        (data[1] = 0x00, status 0x20), exactly like a physical Eltako rocker
        and the actor's own confirmation telegrams. The release MUST be a real
        0x00/0x20 release, not a second pressed-status telegram: an Eltako
        FSB61 only treats a *completed* short press as the "step/stop" event
        that halts mid-travel. A malformed release still starts travel but is
        never recognized as a stop.
        """
        chan_low = (channel * 2) * 0x10
        chan_high = chan_low + 0x10
        data_h = [0xF6, chan_high]
        data_h.extend(self.dev_id)
        data_h.extend([0x30])
        data_l = [0xF6, 0x00]
        data_l.extend(self.dev_id)
        data_l.extend([0x20])
        optional = [0x01, ]
        optional.extend(self.broadcast_id)
        optional.extend([0xff, 0x00])
        self.send_command(data=data_h, optional=optional, packet_type=0x01)
        time.sleep(CONST_SHORT_PRESS)
        self.send_command(data=data_l, optional=optional, packet_type=0x01)

    def open_cover(self, **kwargs):
        """Open the cover (tap the up channel)."""
        _LOGGER.debug("Open cover %s (channel_up %d)",
                      self._devname, self.channel_up)
        self._send_tap(self.channel_up)
        self._state.start_opening()
        self._restart_timer()
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs):
        """Close the cover (tap the down channel)."""
        _LOGGER.debug("Close cover %s (channel_down %d)",
                      self._devname, self.channel_down)
        self._send_tap(self.channel_down)
        self._state.start_closing()
        self._restart_timer()
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop a running travel by tapping the active direction again.

        A repeated short tap halts an Eltako FSB61 mid-travel. If we do not
        believe the cover is moving, we do nothing (a tap would otherwise
        START a movement).
        """
        if self._state.is_opening:
            _LOGGER.debug("Stop cover %s: opening -> tap channel_up %d",
                          self._devname, self.channel_up)
            self._send_tap(self.channel_up)
        elif self._state.is_closing:
            _LOGGER.debug("Stop cover %s: closing -> tap channel_down %d",
                          self._devname, self.channel_down)
            self._send_tap(self.channel_down)
        else:
            _LOGGER.debug("Stop ignored, %s not moving", self._devname)
            return
        self._cancel_timer()
        self._state.stop()
        _LOGGER.debug("Stop cover %s: state set to stopped (unknown)",
                      self._devname)
        self.schedule_update_ha_state()

    def _restart_timer(self):
        """(Re)start the travel-time timer that lands on an end state."""
        self._cancel_timer()
        self._timer = threading.Timer(self._travel_time, self._on_timer)
        self._timer.start()

    def _cancel_timer(self):
        """Cancel a pending travel-time timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_timer(self):
        """Travel time elapsed: settle into open/closed."""
        self._timer = None
        self._state.finish_motion()
        self.schedule_update_ha_state()

    def value_changed(self, code):
        """Handle an actor confirmation telegram (raw RPS data[1] code).

        Lets HA mirror movements that were triggered at the wall switch.
        """
        _LOGGER.debug("Cover %s actor code %s",
                      self._devname, format(code, '#04x'))
        was_opening = self._state.is_opening
        was_closing = self._state.is_closing
        result = self._state.on_feedback(code)
        if result is None:
            _LOGGER.debug("Cover %s ignoring code %s",
                          self._devname, format(code, '#04x'))
            return
        _LOGGER.debug("Cover %s feedback %s -> '%s' (was opening=%s closing=%s)"
                      ", restarting %ds timer",
                      self._devname, format(code, '#04x'), result,
                      was_opening, was_closing, self._travel_time)
        self._restart_timer()
        self.schedule_update_ha_state()
