"""Collector for rocker teach-in candidates (HA-free)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Collection

if TYPE_CHECKING:  # annotation only; keeps the module importable both
    from .rocker import RockerAction  # in the HA package and in tests


@dataclass
class Candidate:
    sender: int
    button: str
    released: bool
    last_press: float
    released_at: float | None = None


class TeachCollector:
    """Collect senders while the user presses a rocker.

    A real rocker sends press followed by release; Eltako actors only send
    press-like status telegrams and never a release.
    """

    def __init__(self, only_sender: int | None = None, settle_s: float = 2.0) -> None:
        self._only_sender = only_sender
        self._settle_s = settle_s
        self._cands: dict[int, Candidate] = {}

    def feed(self, sender: int, action: RockerAction, t: float) -> None:
        if self._only_sender is not None and sender != self._only_sender:
            return
        cand = self._cands.get(sender)
        if action.pressed:
            if cand is None:
                self._cands[sender] = Candidate(
                    sender, action.button, False, t, None
                )
            else:
                cand.last_press = t
        elif cand is not None:
            cand.released = True
            cand.released_at = t

    def ready(self, t: float) -> bool:
        return any(
            c.released and t - c.released_at >= self._settle_s
            for c in self._cands.values()
        )

    def candidates(self) -> list[Candidate]:
        return sorted(
            self._cands.values(), key=lambda c: (not c.released, -c.last_press)
        )

    def preselect(self, known: Collection[int] = ()) -> Candidate | None:
        """Best released candidate; senders in ``known`` (already taught) last."""
        released = [c for c in self.candidates() if c.released]
        for c in released:
            if c.sender not in known:
                return c
        return released[0] if released else None
