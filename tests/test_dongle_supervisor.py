"""Unit tests for the EnOcean communicator supervisor."""
import logging
import time

from dongle_supervisor import CommunicatorSupervisor

PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A60149N0-if00-port0"


class FakeCommunicator:
    def __init__(self, port):
        self.port = port
        self.alive = False
        self.sent = []
        self.stopped = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def send(self, packet):
        self.sent.append(packet)
        return True

    def stop(self):
        self.stopped = True
        self.alive = False


class Harness:
    def __init__(self, present=True):
        self.present = present
        self.created = []
        self.fail_open = False

    def factory(self, port):
        if self.fail_open:
            raise OSError("could not open port")
        comm = FakeCommunicator(port)
        self.created.append(comm)
        return comm

    def path_exists(self, port):
        return self.present

    def supervisor(self, interval=10.0):
        return CommunicatorSupervisor(PORT, self.factory, interval=interval,
                                      path_exists=self.path_exists)


def test_connects_when_device_present():
    h = Harness(present=True)
    sup = h.supervisor()
    assert sup.check() is True
    assert len(h.created) == 1
    assert h.created[0].alive is True
    assert sup.state == "connected"


def test_starts_without_device():
    h = Harness(present=False)
    sup = h.supervisor()
    assert sup.check() is False
    assert h.created == []
    assert sup.state == "waiting"
    h.present = True
    assert sup.check() is True
    assert len(h.created) == 1


def test_reconnects_after_thread_death():
    h = Harness()
    sup = h.supervisor()
    sup.check()
    h.created[0].alive = False          # SerialCommunicator thread died
    assert sup.check() is True
    assert len(h.created) == 2
    assert sup.state == "connected"


def test_waits_while_device_gone_after_loss():
    h = Harness()
    sup = h.supervisor()
    sup.check()
    h.created[0].alive = False
    h.present = False
    assert sup.check() is False
    assert sup.state == "waiting"
    assert len(h.created) == 1


def test_open_failure_is_retried():
    h = Harness()
    h.fail_open = True
    sup = h.supervisor()
    assert sup.check() is False
    assert sup.state == "open_failed"
    h.fail_open = False
    assert sup.check() is True


def test_send_while_disconnected_warns_and_drops(caplog):
    h = Harness(present=False)
    sup = h.supervisor()
    sup.check()
    with caplog.at_level(logging.WARNING):
        assert sup.send("packet") is False
    assert any("not connected" in r.getMessage() for r in caplog.records)


def test_send_while_connected_forwards():
    h = Harness()
    sup = h.supervisor()
    sup.check()
    assert sup.send("packet") is True
    assert h.created[0].sent == ["packet"]


def test_state_change_logged_once(caplog):
    h = Harness(present=False)
    sup = h.supervisor()
    with caplog.at_level(logging.INFO):
        sup.check()
        sup.check()
        sup.check()
    waiting = [r for r in caplog.records if "not present" in r.getMessage()]
    assert len(waiting) == 1


def test_background_thread_recovers_and_stop_ends_it():
    h = Harness()
    sup = h.supervisor(interval=0.02)
    sup.start()
    h.created[0].alive = False
    deadline = time.time() + 2
    while len(h.created) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert len(h.created) == 2
    sup.stop()
    assert h.created[-1].stopped is True
    sup._thread.join(timeout=2)
    assert not sup._thread.is_alive()
