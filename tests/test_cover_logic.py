"""Unit tests for the pure shutter state machine."""
# Imported as a bare module (not enoceanbt.cover_logic) so the package
# __init__.py — which imports Home Assistant — is not executed locally.
from cover_logic import ShutterState, CODE_UP, CODE_DOWN


def test_initial_state_is_unknown():
    s = ShutterState()
    assert s.is_closed is None
    assert s.is_opening is False
    assert s.is_closing is False
    assert s.is_moving is False


def test_start_opening_sets_opening_flags():
    s = ShutterState()
    s.start_opening()
    assert s.is_opening is True
    assert s.is_closing is False
    assert s.is_closed is None
    assert s.is_moving is True


def test_start_closing_sets_closing_flags():
    s = ShutterState()
    s.start_closing()
    assert s.is_closing is True
    assert s.is_opening is False
    assert s.is_moving is True


def test_finish_after_opening_is_open():
    s = ShutterState()
    s.start_opening()
    s.finish_motion()
    assert s.is_closed is False
    assert s.is_moving is False


def test_finish_after_closing_is_closed():
    s = ShutterState()
    s.start_closing()
    s.finish_motion()
    assert s.is_closed is True
    assert s.is_moving is False


def test_stop_leaves_intermediate_unknown():
    s = ShutterState()
    s.start_opening()
    s.stop()
    assert s.is_closed is None
    assert s.is_moving is False


def test_feedback_up_returns_open_and_starts_opening():
    s = ShutterState()
    assert s.on_feedback(CODE_UP) == 'open'
    assert s.is_opening is True


def test_feedback_down_returns_close_and_starts_closing():
    s = ShutterState()
    assert s.on_feedback(CODE_DOWN) == 'close'
    assert s.is_closing is True


def test_feedback_unknown_code_is_ignored():
    s = ShutterState()
    assert s.on_feedback(0x30) is None
    assert s.is_moving is False
    assert s.is_closed is None
