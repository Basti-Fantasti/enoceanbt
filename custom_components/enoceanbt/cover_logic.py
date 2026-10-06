"""Pure state logic for EnOcean covers (no Home Assistant dependencies).

Kept HA-agnostic so the state machine can be unit-tested in isolation.
The owning entity drives the travel-time timer and calls finish_motion()
when it elapses.
"""

# Actor confirmation codes carried in RPS data[1].
CODE_UP = 0x70
CODE_DOWN = 0x50


class ShutterState:
    """Tracks open/closed/moving state of a time-based roller shutter."""

    def __init__(self):
        self._closed = None      # None = unknown, True = closed, False = open
        self._opening = False
        self._closing = False

    @property
    def is_closed(self):
        return self._closed

    @property
    def is_opening(self):
        return self._opening

    @property
    def is_closing(self):
        return self._closing

    @property
    def is_moving(self):
        return self._opening or self._closing

    def start_opening(self):
        """Begin an opening movement."""
        self._closed = None
        self._opening = True
        self._closing = False

    def start_closing(self):
        """Begin a closing movement."""
        self._closed = None
        self._opening = False
        self._closing = True

    def stop(self):
        """Halt motion at an intermediate (unknown) position."""
        self._opening = False
        self._closing = False
        self._closed = None

    def finish_motion(self):
        """Called when the travel-time timer elapses: land on an end state."""
        if self._closing:
            self._closed = True
        elif self._opening:
            self._closed = False
        self._opening = False
        self._closing = False

    def on_feedback(self, code):
        """Handle an actor confirmation code.

        Returns 'open'/'close' if the caller should (re)start a motion timer,
        or None if the code is irrelevant.
        """
        if code == CODE_UP:
            self.start_opening()
            return 'open'
        if code == CODE_DOWN:
            self.start_closing()
            return 'close'
        return None
