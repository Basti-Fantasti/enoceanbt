"""EnOcean F6 (RPS) rocker decoding, short/long press tracking and mapping.

Pure Python, no Home Assistant imports.
"""
from __future__ import annotations

from dataclasses import dataclass

BUTTONS = ("AI", "AO", "BI", "BO")  # index = R1 value 0..3

_RORG_RPS = 0xF6
_NU_BIT = 0x10


@dataclass(frozen=True)
class RockerAction:
    button: str | None
    pressed: bool


def decode(rorg: int, data1: int, status: int) -> RockerAction | None:
    """Decode an RPS telegram into a rocker action, or None if irrelevant."""
    if rorg != _RORG_RPS:
        return None
    if status & _NU_BIT:
        return RockerAction(BUTTONS[(data1 >> 5) & 0x03], True)
    if data1 == 0x00:
        return RockerAction(None, False)
    return None


@dataclass(frozen=True)
class RockerEvent:
    button: str
    event_type: str  # "press" | "short_release" | "long_release"
    duration: float | None


class RockerTracker:
    """Turns press/release actions into press and short/long release events."""

    def __init__(self, long_press_s: float = 0.5, repeat_s: float = 0.3) -> None:
        self._long_press_s = long_press_s
        self._repeat_s = repeat_s
        self._button: str | None = None
        self._t_press = 0.0
        self._t_last = 0.0

    def handle(self, action: RockerAction, t: float) -> list[RockerEvent]:
        if action.pressed:
            if (
                self._button == action.button
                and t - self._t_last < self._repeat_s
            ):
                self._t_last = t
                return []
            self._button = action.button
            self._t_press = t
            self._t_last = t
            return [RockerEvent(action.button, "press", None)]
        if self._button is None:
            return []
        button = self._button
        duration = t - self._t_press
        self._button = None
        kind = "long_release" if duration >= self._long_press_s else "short_release"
        return [RockerEvent(button, kind, duration)]


class MappingError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def derive_mapping(layout: str, first: str, second: str) -> dict:
    """Derive a button-to-position mapping from two pressed buttons."""
    if first == second:
        raise MappingError("same_button")
    up = first[1]
    if layout == "2x2":
        if first[0] == second[0] or first[1] == second[1]:
            raise MappingError("wrong_pair")
        return {
            "layout": "2x2",
            "left": first[0],
            "right": second[0],
            "up": up,
            "down": "O" if up == "I" else "I",
        }
    if layout == "1x2":
        if first[0] != second[0]:
            raise MappingError("wrong_pair")
        return {"layout": "1x2", "channel": first[0], "up": up, "down": second[1]}
    raise ValueError(f"unknown layout {layout!r}")


def keys_for_layout(layout: str) -> tuple[str, ...]:
    if layout == "2x2":
        return ("left_up", "left_down", "right_up", "right_down")
    if layout == "1x2":
        return ("up", "down")
    raise ValueError(f"unknown layout {layout!r}")


def key_for(mapping: dict, button: str) -> str | None:
    channel, direction = button[0], button[1]
    pos = (
        "up" if direction == mapping["up"]
        else "down" if direction == mapping["down"]
        else None
    )
    if pos is None:
        return None
    if mapping["layout"] == "2x2":
        if channel == mapping["left"]:
            return f"left_{pos}"
        if channel == mapping["right"]:
            return f"right_{pos}"
        return None
    return pos if channel == mapping["channel"] else None
