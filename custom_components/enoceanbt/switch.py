"""
Support for EnOcean switches.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/switch.enocean/



Modified for Eltako actors FSR61 and FSB61

parameters:

id: (Required)
    Old implementation: The ID of the device.
    This is a 4 Byte long number.
    New:
    Is the 4 byte long BaseID of the USB300 device
    If you don't use the BaseID of your USB300 the
    ChipID is used, which limits the amount of actors
    you can communicate with to the amount of channels
    (e.g. 4 for "Dual Rocker" emulation)

    It's not possible to use a generic ID due to
    EnOceans security approach to avoid faking of existing IDs

    This BaseID can be determined using several ways:

    1. Using a terminal program
    - Open serial connection to USB300 (57600,8,1,n)
    - send ESP3 common command CO_RD_IDBASE to USB300:
        0x55 0x00 0x01 0x00 0x05 0x70 0x08 0x38
    - Response:
        0x55 0x00 0x05 0x01 0x02 0xDB 0x00 0xMY 0xBA 0xSE 0xID 0x0A 0x64
    - You find the BaseID here: 0xMY 0xBA 0xSE 0xID

    2. Using Dolphin View Advance Software on Windows
    - Plug in the USB300
    - Start Dolphin View Advance
    - Press Connect
    - Go To "Telegram Transmit" Tab
    - Click on "Add operation"
    - Select "Send ESP3 packet"
    - Enter Type: 05, Data: 08
    - Highlight the command
    - Click "Execute selected"
    - In the Telegram Log switch to "Serial"
    - Find your ID in the response line in the same format as above

channel: Optional, Default = 0
    For the old implementation channel remains the same
    for the wallswitch emulation the channel parameter is
    the ON channel (0-3)

channel_off: Optional, Default = 0, only used if type_wallswitch = 1
    Set the channel_off parameter to the same value as "channel"
    if you only want to toggle an actor (like teaching the same Rocker
    for on and off.

    If two different channels should be configured for ON and OFF
    it can be done setting channel_off to a different channel then "channel"

actor_id: Optional, Default [0xFF,0xFF,0xFF,0xFF],
          only used if type_wallswitch = 1
    parameter to receive status telegrams from actor (if enabled)
    if ID is given, the HA UI will update accordingly when another switch
    toggles an actor (e.g. physical wallswitch turns actor on/off)

long_press: Default 0, only used if type_wallswitch = 1
    The Eltako switches can be configured for different behaviours
    on long and short button press.
    Default is a short press to turn on / off an actor
    In addition a long press can turn on an actor for a predefined
    time. (long_press = 1)
    Please refer to the Eltako FSR61 manual on the possible modes
    Due to the different period of time it's necessary to send a
    second telegram after the delay to release the switch (High->Low)

type_wallswitch: Default: 0, Set this to 1 to use the
    Eltako implementation and send RPS telegrams using BaseID+Offset

base_id_offset: Default 0, only used if type_wallswitch = 1
    The base_id_offset is used to extend the amount of simulated
    enocean devices.
    The value set as base_id_offset is added to the last byte
    of the BaseID
    The value can be from 0..127
    So a total of 128*4 channels can be used for different devices

Examples:

switch eltakoFSR61_00:
    - platform: enocean
      name: Office Light
      id: [0xFF,0xAB,0xCD,0x80]
      base_id_offset: 0
      channel: 0
      channel_off: 0
      long_press: 0
      type_wallswitch: 1
      actor_id: [0xAA,0xBB,0xCC,0xDD]


switch eltakoFSB61_00:
    - platform: enocean
      name: Office Blinds Up
      id: [0xFF,0xAB,0xCD,0x80]
      base_id_offset: 1
      channel: 0
      channel_off: 0
      long_press: 0
      type_wallswitch: 1
      actor_id: [0xAB,0xBA,0xCA,0xDA]

switch eltakoFSB61_01:
    - platform: enocean
      name: Office Blinds Down
      id: [0xFF,0xAB,0xCD,0x80]
      base_id_offset: 1
      channel: 1
      channel_off: 1
      long_press: 0
      type_wallswitch: 1
      actor_id: [0xFF,0xFF,0xFF,0xFF]

"""

import logging
import time
import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA
from homeassistant.const import (CONF_NAME, CONF_ID)
# from homeassistant.custom_components import enoceanbt
from custom_components import enoceanbt
from homeassistant.helpers.entity import ToggleEntity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'EnOceanBt Switch'
# DEPENDENCIES = ['enocean']
CONF_CHANNEL = 'channel'
CONF_CHAN_OFF = 'channel_off'
CONF_ACT_ID = 'actor_id'
CONF_LNG_PR = 'long_press'
CONF_TYPE_WS = 'type_wallswitch'
CONF_BASE_ID_OFFSET = 'base_id_offset'
CONST_SHORT_PRESS = 0.3
CONST_LONG_PRESS = 1.5

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_CHANNEL, default=0): cv.positive_int,
    vol.Optional(CONF_CHAN_OFF, default=0): cv.positive_int,
    vol.Optional(CONF_ACT_ID, default=[0xff, 0xff, 0xff, 0xff]):
        vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_LNG_PR, default=0): cv.positive_int,
    vol.Optional(CONF_TYPE_WS, default=0): cv.positive_int,
    vol.Optional(CONF_BASE_ID_OFFSET, default=0): cv.positive_int,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the EnOcean switch platform."""
    dev_id = config.get(CONF_ID)
    devname = config.get(CONF_NAME)
    channel = config.get(CONF_CHANNEL)
    chan_off_id = config.get(CONF_CHAN_OFF)
    actor_id = config.get(CONF_ACT_ID)
    longpr = config.get(CONF_LNG_PR)
    type_ws = config.get(CONF_TYPE_WS)
    b_id_offset = config.get(CONF_BASE_ID_OFFSET)

    add_entities([EnOceanSwitch(dev_id, b_id_offset, actor_id,
                                devname, channel, chan_off_id,
                                longpr, type_ws)])


class EnOceanSwitch(enoceanbt.EnOceanDevice, ToggleEntity):
    """Representation of an EnOcean switch device."""

    def __init__(self, dev_id, b_id_offset, actor_id, devname, channel,
                 chan_off_id, longpr, type_ws):
        """Initialize the EnOcean switch device."""
        enoceanbt.EnOceanDevice.__init__(self)
        self.dev_id = dev_id
        self.dev_id[3] = self.dev_id[3] + b_id_offset
        self.actor_id = actor_id
        self.broadcast_id = [0xff, 0xff, 0xff, 0xff]
        self._devname = devname
        self._light = None
        self._on_state = False
        self._on_state2 = False
        self.channel = channel
        self.stype = "switch"
        self.is_type_ws = False
        if type_ws > 0:
            self.is_type_ws = True
        self.chan_on_low = (channel*2) * 0x10
        self.chan_on_high = self.chan_on_low + 0x10
        self.chan_off_low = (chan_off_id*2) * 0x10
        self.chan_off_high = self.chan_off_low + 0x10
        self.press_duration = CONST_SHORT_PRESS
        if longpr > 0:
            self.press_duration = CONST_LONG_PRESS

    @property
    def is_on(self):
        """Return whether the switch is on or off."""
        return self._on_state

    @property
    def name(self):
        """Return the device name."""
        return self._devname

    def turn_on(self, **kwargs):
        """Turn on the switch."""
        if self.is_type_ws:
            _LOGGER.debug("Turn ON switch: %s BaseID: (%s) "
                          "High: %s Low: %s Delay: %.1f",
                          self._devname, format(self.dev_id[3], '#04x'),
                          format(self.chan_on_high, '#04x'),
                          format(self.chan_on_low, '#04x'),
                          self.press_duration)
            data_h = [0xF6, self.chan_on_high]
            data_h.extend(self.dev_id)
            data_h.extend([0x30])
            data_l = [0xF6, self.chan_on_low]
            data_l.extend(self.dev_id)
            data_l.extend([0x30])
            optional = [0x01, ]
            optional.extend(self.broadcast_id)
            optional.extend([0xff, 0x00])
            self.send_command(data=data_h, optional=optional, packet_type=0x01)
            time.sleep(self.press_duration)
            self.send_command(data=data_l, optional=optional, packet_type=0x01)
            if self.chan_on_high != self.chan_off_high:
                self._on_state = True
            else:
                self._on_state = False
        else:
            optional = [0x03, ]
            optional.extend(self.dev_id)
            optional.extend([0xff, 0x00])
            self.send_command(data=[0xD2, 0x01, self.channel & 0xFF, 0x64,
                                    0x00, 0x00, 0x00, 0x00, 0x00],
                              optional=optional, packet_type=0x01)
            self._on_state = True

    def turn_off(self, **kwargs):
        """Turn off the switch."""
        if self.is_type_ws:
            _LOGGER.debug("Turn OFF switch: %s BaseID: (%s) "
                          "High: %s Low: %s Delay: %.1f",
                          self._devname, format(self.dev_id[3], '#04x'),
                          format(self.chan_off_high, '#04x'),
                          format(self.chan_off_low, '#04x'),
                          self.press_duration)
            data_h = [0xF6, self.chan_off_high]
            data_h.extend(self.dev_id)
            data_h.extend([0x30])
            data_l = [0xF6, self.chan_off_low]
            data_l.extend(self.dev_id)
            data_l.extend([0x30])
            optional = [0x01, ]
            optional.extend(self.broadcast_id)
            optional.extend([0xff, 0x00])
            self.send_command(data=data_h, optional=optional, packet_type=0x01)
            time.sleep(self.press_duration)
            self.send_command(data=data_l, optional=optional, packet_type=0x01)
            self._on_state = False
        else:
            optional = [0x03, ]
            optional.extend(self.dev_id)
            optional.extend([0xff, 0x00])
            self.send_command(data=[0xD2, 0x01, self.channel & 0xFF, 0x00,
                                    0x00, 0x00, 0x00, 0x00, 0x00],
                              optional=optional, packet_type=0x01)
            self._on_state = False

    def value_changed(self, val):
        """Update the internal state of the switch."""
        _LOGGER.debug("set new value: %s %d", self._devname,  val)
        self._on_state = val
        self.schedule_update_ha_state()
