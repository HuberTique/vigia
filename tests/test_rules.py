from datetime import datetime, timedelta

from vigia.rules import AbandonedObjectRule, IntrusionRule, LoiteringRule
from vigia.types import FrameContext, TrackedObject
from vigia.zones import Schedule, Zone, point_in_polygon

W, H = 1000, 1000
NIGHT = datetime(2026, 10, 10, 23, 0, 0)
DAY = datetime(2026, 10, 10, 12, 0, 0)

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def person(tid, cx, foot_y, h=200):
    return TrackedObject(tid, "person", 0.9, cx - 40, foot_y - h, cx + 40, foot_y)


def bag(tid, cx, cy, size=60, cls="backpack"):
    return TrackedObject(tid, cls, 0.8, cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)


def run(rule, frames, start=NIGHT, fps=5):
    """frames: lista de listas de objetos, uno por cuadro a ``fps``."""
    events = []
    for i, objs in enumerate(frames):
        t = i / fps
        events += rule.update(FrameContext("cam", t, start + timedelta(seconds=t), W, H, objs))
    return events


# --- zonas -----------------------------------------------------------------


def test_point_in_polygon():
    assert point_in_polygon(0.5, 0.5, SQUARE)
    assert not point_in_polygon(0.1, 0.5, SQUARE)


def test_schedule_crossing_midnight():
    s = Schedule.parse("22:00-06:00")
    assert s.active(NIGHT)
    assert s.active(datetime(2026, 10, 11, 3, 0))
    assert not s.active(DAY)


# --- merodeo ---------------------------------------------------------------


def test_loitering_alerts_once_after_dwell():
    rule = LoiteringRule([Zone("anden", "loitering", SQUARE)], dwell_seconds=10)
    frames = [[person(1, 500, 600)]] * (15 * 5)  # 15 s quieto dentro
    events = run(rule, frames)
    assert len(events) == 1
    assert events[0].track_ids == [1]
    assert 10 <= events[0].t < 10.5


def test_loitering_passerby_does_not_alert():
    rule = LoiteringRule([Zone("anden", "loitering", SQUARE)], dwell_seconds=10)
    frames = [[person(1, 300 + i * 10, 600)] for i in range(40)]  # cruza en 8 s
    assert run(rule, frames) == []


def test_loitering_tolerates_short_occlusion_but_resets_after_grace():
    zone = Zone("anden", "loitering", SQUARE)
    inside = [[person(1, 500, 600)]]
    gone = [[]]
    # 6 s dentro, 1 s oculto, 6 s dentro: suma 12 s con grace 3 -> alerta
    assert len(run(LoiteringRule([zone], dwell_seconds=10, grace_seconds=3), inside * 30 + gone * 5 + inside * 30)) == 1
    # 6 s dentro, 5 s fuera, 6 s dentro: se reinicia -> sin alerta
    assert run(LoiteringRule([zone], dwell_seconds=10, grace_seconds=3), inside * 30 + gone * 25 + inside * 30) == []


def test_loitering_ignores_other_classes():
    rule = LoiteringRule([Zone("anden", "loitering", SQUARE)], dwell_seconds=1)
    assert run(rule, [[bag(1, 500, 500)]] * 20) == []


# --- intrusión -------------------------------------------------------------


def test_door_intrusion_only_inside_schedule():
    door = Zone("puerta", "door", SQUARE, schedules=[Schedule.parse("22:00-06:00")])
    frames = [[person(7, 500, 600)]] * 10
    assert len(run(IntrusionRule([door]), frames, start=NIGHT)) == 1
    assert run(IntrusionRule([door]), frames, start=DAY) == []


def test_window_intrusion_uses_body_center():
    # Ventana alta: los pies quedan por debajo de la ventana pero el cuerpo está dentro.
    window = Zone("ventana", "window", [(0.4, 0.1), (0.6, 0.1), (0.6, 0.4), (0.4, 0.4)])
    climbing = TrackedObject(3, "person", 0.9, 450, 200, 550, 500)  # centro y=350 dentro, pies y=500 fuera
    events = run(IntrusionRule([window]), [[climbing]] * 10, start=DAY)
    assert len(events) == 1
    assert events[0].severity == "high"
    assert "ventana" in events[0].message


def test_intrusion_requires_confirmation():
    zone = Zone("bodega", "restricted", SQUARE)
    one_frame = [[person(1, 500, 600)]] + [[]] * 10
    assert run(IntrusionRule([zone], confirm_seconds=1.0), one_frame) == []


# --- objeto abandonado -----------------------------------------------------


def test_abandoned_bag_after_owner_leaves():
    rule = AbandonedObjectRule(static_seconds=10, unattended_seconds=5)
    with_owner = [[bag(10, 500, 700), person(1, 520, 760)]] * (6 * 5)
    owner_walks_away = [[bag(10, 500, 700), person(1, 520 + i * 40, 760)] for i in range(10)]
    alone = [[bag(10, 500, 700)]] * (12 * 5)
    events = run(rule, with_owner + owner_walks_away + alone)
    assert len(events) == 1
    assert events[0].rule == "abandoned_object"


def test_attended_bag_does_not_alert():
    rule = AbandonedObjectRule(static_seconds=5, unattended_seconds=5)
    assert run(rule, [[bag(10, 500, 700), person(1, 520, 760)]] * (30 * 5)) == []


def test_abandoned_bag_survives_tracker_id_changes():
    # Alguien pasa por delante y el tracker le cambia el ID a la mochila en cada cuadro.
    rule = AbandonedObjectRule(static_seconds=5, unattended_seconds=5)
    frames = [[bag(100 + i, 500, 700)] for i in range(12 * 5)]
    assert len(run(rule, frames)) == 1


def test_carried_bag_does_not_alert():
    rule = AbandonedObjectRule(static_seconds=5, unattended_seconds=1)
    frames = [[bag(10, 100 + i * 15, 700)] for i in range(50)]  # se mueve
    assert run(rule, frames) == []
