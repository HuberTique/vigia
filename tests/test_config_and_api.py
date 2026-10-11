from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vigia.api import create_app
from vigia.config import load_config
from vigia.events import EventStore
from vigia.rules import IntrusionRule, LoiteringRule
from vigia.types import Event

ROOT = Path(__file__).resolve().parents[1]


def test_demo_config_builds_rules():
    cfg = load_config(ROOT / "configs" / "demo.yaml")
    cam = cfg.cameras[0]
    rules = cam.build_rules()
    kinds = {type(r) for r in rules}
    assert {LoiteringRule, IntrusionRule} <= kinds
    loiter = next(r for r in rules if isinstance(r, LoiteringRule))
    assert [z.name for z in loiter.zones] == ["anden"]


def test_config_rejects_unknown_zone(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("cameras:\n  - id: a\n    source: x.mp4\n    rules:\n      loitering: {zones: [nope]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="zonas inexistentes"):
        load_config(p).cameras[0].build_rules()


def test_config_rejects_pixel_coordinates(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "cameras:\n  - id: a\n    source: x.mp4\n    zones:\n      - {name: z, polygon: [[10, 10], [200, 10], [200, 200]]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="normalizadas"):
        load_config(p)


def test_api_lists_and_reviews_events(tmp_path):
    store = EventStore(tmp_path)
    eid = store.add(Event("cam1", "loitering", 12.0, datetime(2026, 10, 10, 23, 0), "Persona #1 lleva 60 s", zone="anden"))
    client = TestClient(create_app(str(tmp_path)))

    events = client.get("/events").json()
    assert [e["id"] for e in events] == [eid]

    r = client.post(f"/events/{eid}/review", json={"review": "false_alarm"})
    assert r.status_code == 200 and r.json()["review"] == "false_alarm"
    assert client.post(f"/events/{eid}/review", json={"review": "maybe"}).status_code == 422
    assert client.get(f"/events/{eid}/snapshot").status_code == 404
    assert client.get("/").status_code == 200
