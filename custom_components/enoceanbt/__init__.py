"""Support for EnOcean devices."""
import logging
import time

import voluptuous as vol

from homeassistant.const import CONF_DEVICE, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .hub import RockerHub

# REQUIREMENTS = ['enocean==0.40']

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'enoceanbt'

ENOCEAN_DONGLE = None

PLATFORMS = [Platform.EVENT]

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_DEVICE): cv.string,
    }),
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Set up the EnOcean component."""
    global ENOCEAN_DONGLE

    # Hub first, so config entries can load (hub.connected is False) even
    # without a YAML block.
    hass.data[DOMAIN] = {"hub": RockerHub(hass, lambda: ENOCEAN_DONGLE)}

    if DOMAIN not in config:
        return True

    serial_dev = config[DOMAIN].get(CONF_DEVICE)

    ENOCEAN_DONGLE = EnOceanDongle(hass, serial_dev)

    return True


async def async_setup_entry(hass, entry):
    """Set up one taught rocker switch from a config entry."""
    if DOMAIN not in hass.data:
        raise ConfigEntryNotReady("enoceanbt YAML setup has not run yet")
    hub = hass.data[DOMAIN]["hub"]
    hub.register(entry.data["address"])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    area_id = entry.data.get("area_id")
    if area_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{entry.data['address']:08X}")})
        if device is not None and device.area_id is None:
            dev_reg.async_update_device(device.id, area_id=area_id)
    return True


async def async_unload_entry(hass, entry):
    """Unload a rocker switch config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS)
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN]["hub"].unregister(entry.data["address"])
    return unload_ok


class EnOceanDongle:
    """Representation of an EnOcean dongle."""

    def __init__(self, hass, ser):
        """Initialize the EnOcean dongle."""
        from enocean.communicators.serialcommunicator import SerialCommunicator
        from .dongle_supervisor import CommunicatorSupervisor
        self._hass = hass
        self.__devices = []
        self.__supervisor = CommunicatorSupervisor(
            ser, lambda port: SerialCommunicator(port=port, callback=self.callback))
        self.__supervisor.start()
        hass.bus.listen_once(
            EVENT_HOMEASSISTANT_STOP, lambda event: self.__supervisor.stop())

    @property
    def devices(self):
        """Registered YAML devices."""
        return self.__devices

    @property
    def connected(self):
        """True if the serial communicator is connected."""
        return self.__supervisor.state == "connected"

    def register_device(self, dev):
        """Register another device."""
        self.__devices.append(dev)

    def send_command(self, command):
        """Send a command from the EnOcean dongle."""
        self.__supervisor.send(command)

    # pylint: disable=no-self-use
    def _combine_hex(self, data):
        """Combine list of integer values to one big integer."""
        output = 0x00
        for i, j in enumerate(reversed(data)):
            output |= (j << i * 8)
        return output

    def callback(self, temp):
        """Handle EnOcean device's callback.

        This is the callback function called by python-enocan whenever there
        is an incoming packet.
        """
        from enocean.protocol.packet import RadioPacket
        if isinstance(temp, RadioPacket):
            if temp.data[0] == 0xF6:
                hub = self._hass.data[DOMAIN]["hub"]
                try:
                    self._hass.loop.call_soon_threadsafe(
                        hub.handle_raw, temp.sender_int, temp.data[1],
                        temp.data[6], time.monotonic())
                except RuntimeError:
                    pass  # event loop closed during shutdown
            _LOGGER.debug("Received freaking radio packet: %s", temp)
            rxtype = None
            value = None
            channel = 0
            # _LOGGER.debug("byte6: %s", temp.data[6])
            if temp.data[6] == 0x30:
                rxtype = "wallswitch"
                value = 1
            elif temp.data[6] == 0x20:
                rxtype = "wallswitch"
                value = 0
            elif temp.data[4] == 0x0c:
                rxtype = "power"
                value = temp.data[3] + (temp.data[2] << 8)
            elif temp.data[2] & 0x60 == 0x60:
                rxtype = "switch_status"
                channel = temp.data[2] & 0x1F
                if temp.data[3] == 0xe4:
                    value = 1
                elif temp.data[3] == 0x80:
                    value = 0
            elif temp.data[0] == 0xa5 and temp.data[1] == 0x02:
                rxtype = "dimmerstatus"
                value = temp.data[2]
            # eltako actors
            if temp.data[6] == 0x30 and temp.data[0] == 0xf6:
                _LOGGER.debug("Received telegram from actor")
                rxtype = "actor"
                if temp.data[1] == 0x70:
                    value = 1
                    _LOGGER.debug("state on")
                elif temp.data[1] == 0x50:
                    value = 0
                    _LOGGER.debug("state off")
                else:
                    rxtype = ""
                if rxtype != "":
                    aid = [temp.data[2], temp.data[3],
                           temp.data[4], temp.data[5]]
            for device in self.__devices:
                # additional case for eltako actors
                if rxtype == "actor" and device.stype == "switch":
                    if device.actor_id == aid:
                        _LOGGER.debug("Actor found in list! "
                                      "Toggle switch state")
                        if value > 0:
                            device.value_changed(True)
                        else:
                            device.value_changed(False)
                if rxtype == "actor" and device.stype == "cover":
                    if device.actor_id == aid:
                        _LOGGER.debug("Actor found in list! "
                                      "Forward code to cover")
                        device.value_changed(temp.data[1])
                if rxtype == "wallswitch" and device.stype == "listener":
                    if temp.sender_int == self._combine_hex(device.dev_id):
                        device.value_changed(value, temp.data[1])
                if rxtype == "power" and device.stype == "powersensor":
                    if temp.sender_int == self._combine_hex(device.dev_id):
                        device.value_changed(value)
                if rxtype == "power" and device.stype == "switch":
                    if temp.sender_int == self._combine_hex(device.dev_id):
                        if value > 10:
                            device.value_changed(1)
                if rxtype == "switch_status" and device.stype == "switch" and \
                        channel == device.channel:
                    if temp.sender_int == self._combine_hex(device.dev_id):
                        device.value_changed(value)
                if rxtype == "dimmerstatus" and device.stype == "dimmer":
                    if temp.sender_int == self._combine_hex(device.dev_id):
                        device.value_changed(value)


class EnOceanDevice():
    """Parent class for all devices associated with the EnOcean component."""

    def __init__(self):
        """Initialize the device."""
        ENOCEAN_DONGLE.register_device(self)
        self.stype = ""
        self.sensorid = [0x00, 0x00, 0x00, 0x00]

    # pylint: disable=no-self-use
    def send_command(self, data, optional, packet_type):
        """Send a command via the EnOcean dongle."""
        from enocean.protocol.packet import Packet
        packet = Packet(packet_type, data=data, optional=optional)
        ENOCEAN_DONGLE.send_command(packet)
