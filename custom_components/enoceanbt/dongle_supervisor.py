"""Keeps an EnOcean serial communicator running across loss of the USB device.

enocean 0.40's SerialCommunicator thread ends for good on a serial error and
opens the port in its constructor. This supervisor recreates it once the
device path is back. It does not import Home Assistant so it can be unit
tested on its own.
"""
import logging
import os
import threading

_LOGGER = logging.getLogger(__name__)


class CommunicatorSupervisor:
    """Owns the communicator and replaces it after it has died."""

    def __init__(self, port, factory, interval=10.0, path_exists=os.path.exists):
        self._port = port
        self._factory = factory
        self._interval = interval
        self._path_exists = path_exists
        self._communicator = None
        self._stop = threading.Event()
        self._thread = None
        self.state = None

    def _set_state(self, state, level, msg, *args):
        if state != self.state:
            self.state = state
            _LOGGER.log(level, msg, *args)

    def check(self):
        """Run one supervision step. Returns True while a communicator is running."""
        comm = self._communicator
        if comm is not None and comm.is_alive():
            self._set_state("connected", logging.INFO, "EnOcean device %s connected", self._port)
            return True
        if comm is not None:
            self._communicator = None
            self._set_state("lost", logging.WARNING,
                            "EnOcean communicator on %s stopped, waiting for device", self._port)
        if not self._path_exists(self._port):
            self._set_state("waiting", logging.WARNING,
                            "EnOcean device %s not present, waiting", self._port)
            return False
        try:
            comm = self._factory(self._port)
            comm.start()
        except Exception as exc:  # serial errors differ by platform
            self._set_state("open_failed", logging.WARNING,
                            "Opening EnOcean device %s failed: %s", self._port, exc)
            return False
        self._communicator = comm
        self._set_state("connected", logging.INFO, "EnOcean device %s connected", self._port)
        return True

    def send(self, packet):
        """Forward a packet, or drop it with a warning while disconnected."""
        comm = self._communicator
        if comm is None or not comm.is_alive():
            _LOGGER.warning("EnOcean device %s not connected, dropping packet", self._port)
            return False
        comm.send(packet)
        return True

    def _loop(self):
        while not self._stop.wait(self._interval):
            self.check()

    def start(self):
        self.check()
        self._thread = threading.Thread(target=self._loop, name="enoceanbt-supervisor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._communicator is not None:
            self._communicator.stop()
