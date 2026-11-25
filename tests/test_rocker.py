import pytest
from rocker import (decode, RockerAction, RockerTracker, RockerEvent,
                    derive_mapping, MappingError, key_for, keys_for_layout)

def test_decode_press_all_buttons():
    assert decode(0xF6, 0x10, 0x30) == RockerAction("AI", True)
    assert decode(0xF6, 0x30, 0x30) == RockerAction("AO", True)
    assert decode(0xF6, 0x50, 0x30) == RockerAction("BI", True)
    assert decode(0xF6, 0x70, 0x30) == RockerAction("BO", True)

def test_decode_release():
    assert decode(0xF6, 0x00, 0x20) == RockerAction(None, False)

def test_decode_multi_button_release_ignored():
    assert decode(0xF6, 0x15, 0x20) is None

def test_decode_non_rps_ignored():
    assert decode(0xA5, 0x10, 0x30) is None

def test_short_press():
    tr = RockerTracker()
    assert tr.handle(RockerAction("AI", True), 10.0) == [RockerEvent("AI", "press", None)]
    [ev] = tr.handle(RockerAction(None, False), 10.2)
    assert (ev.button, ev.event_type) == ("AI", "short_release")
    assert ev.duration == pytest.approx(0.2)

def test_long_press_boundary():
    tr = RockerTracker()
    tr.handle(RockerAction("BO", True), 0.0)
    [ev] = tr.handle(RockerAction(None, False), 0.5)
    assert ev.event_type == "long_release"

def test_release_without_press_is_ignored():
    assert RockerTracker().handle(RockerAction(None, False), 1.0) == []

def test_lost_release_discards_old_press():
    tr = RockerTracker()
    tr.handle(RockerAction("AI", True), 0.0)
    assert tr.handle(RockerAction("BI", True), 5.0) == [RockerEvent("BI", "press", None)]
    [ev] = tr.handle(RockerAction(None, False), 5.1)
    assert (ev.button, ev.event_type) == ("BI", "short_release")

def test_repeated_press_within_repeat_window_fires_once():
    tr = RockerTracker()
    tr.handle(RockerAction("AI", True), 0.0)
    assert tr.handle(RockerAction("AI", True), 0.1) == []

def test_derive_mapping_2x2():
    assert derive_mapping("2x2", "BO", "AI") == {"layout": "2x2", "left": "B", "right": "A", "up": "O", "down": "I"}

def test_derive_mapping_1x2():
    assert derive_mapping("1x2", "AI", "AO") == {"layout": "1x2", "channel": "A", "up": "I", "down": "O"}

def test_derive_mapping_2x2_rejects_same_channel():
    with pytest.raises(MappingError) as e: derive_mapping("2x2", "AI", "AO")
    assert e.value.reason == "wrong_pair"

def test_derive_mapping_rejects_same_button():
    with pytest.raises(MappingError) as e: derive_mapping("1x2", "AI", "AI")
    assert e.value.reason == "same_button"

def test_derive_mapping_1x2_rejects_other_channel():
    with pytest.raises(MappingError) as e: derive_mapping("1x2", "AI", "BO")
    assert e.value.reason == "wrong_pair"

def test_key_for():
    m = derive_mapping("2x2", "AI", "BO")
    assert [key_for(m, b) for b in ("AI", "AO", "BI", "BO")] == ["left_up", "left_down", "right_up", "right_down"]
    m1 = derive_mapping("1x2", "BI", "BO")
    assert key_for(m1, "AI") is None and key_for(m1, "BO") == "down"

def test_keys_for_layout():
    assert keys_for_layout("1x2") == ("up", "down")

def test_derive_mapping_2x2_rejects_same_direction():
    with pytest.raises(MappingError) as e: derive_mapping("2x2", "AI", "BI")
    assert e.value.reason == "wrong_pair"

def test_keys_for_layout_2x2_and_unknown():
    assert keys_for_layout("2x2") == ("left_up", "left_down", "right_up", "right_down")
    with pytest.raises(ValueError): keys_for_layout("3x3")

def test_same_button_after_repeat_window_gives_new_press():
    tr = RockerTracker()
    tr.handle(RockerAction("AI", True), 0.0)
    assert tr.handle(RockerAction("AI", True), 1.0) == [RockerEvent("AI", "press", None)]
