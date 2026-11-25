from rocker import RockerAction
from teach import TeachCollector

P = lambda b: RockerAction(b, True)
R = RockerAction(None, False)


def test_rocker_with_release_is_ready_after_settle():
    c = TeachCollector()
    c.feed(0x0031E010, P("AI"), 1.0); c.feed(0x0031E010, R, 1.1)
    assert not c.ready(2.0) and c.ready(3.1)
    assert c.preselect().sender == 0x0031E010 and c.preselect().button == "AI"


def test_actor_without_release_not_preselected():
    c = TeachCollector()
    c.feed(0x0031E010, P("AI"), 1.0); c.feed(0x0031E010, R, 1.1)
    c.feed(0x05127C55, P("BO"), 1.3)          # Eltako-Status, kein Release
    assert c.preselect().sender == 0x0031E010
    assert [x.released for x in c.candidates()] == [True, False]


def test_only_actor_seen_is_never_ready():
    c = TeachCollector()
    c.feed(0x05127C55, P("BO"), 1.0)
    assert not c.ready(10.0) and c.preselect() is None


def test_second_step_ignores_other_senders():
    c = TeachCollector(only_sender=0x0031E010, settle_s=0.0)
    c.feed(0x0031D020, P("AO"), 1.0); c.feed(0x0031D020, R, 1.1)
    assert not c.ready(1.2)
    c.feed(0x0031E010, P("BO"), 1.5); c.feed(0x0031E010, R, 1.6)
    assert c.ready(1.6) and c.preselect().button == "BO"


def test_release_before_any_press_ignored():
    c = TeachCollector()
    c.feed(0x0031E010, R, 1.0)
    assert c.candidates() == []
