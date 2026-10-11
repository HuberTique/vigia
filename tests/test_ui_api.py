"""Pruebas de la API que usa la interfaz gráfica (sin modelos reales)."""

import time

import cv2
import numpy as np
import pytest
import supervision as sv
import yaml
from fastapi.testclient import TestClient

from vigia.api import create_app


class FakeDetector:
    """Detecta siempre una persona quieta en el centro de la imagen."""

    def detect(self, frame):
        h, w = frame.shape[:2]
        det = sv.Detections(
            xyxy=np.array([[w * 0.4, h * 0.3, w * 0.6, h * 0.9]], dtype=float),
            confidence=np.array([0.9]),
            class_id=np.array([0]),
        )
        det.data["class_name"] = np.array(["person"], dtype=object)
        return det


@pytest.fixture
def setup(tmp_path):
    video = tmp_path / "v.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    for i in range(30):
        writer.write(np.full((120, 160, 3), i * 8, np.uint8))
    writer.release()

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "analysis_fps": 10,
                "data_dir": str(tmp_path / "data"),
                "cameras": [{"id": "cam1", "name": "Prueba", "source": str(video), "zones": [], "rules": {}}],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(str(tmp_path / "data"), config_path=str(cfg))
    app.state.runner._detector = FakeDetector()
    with TestClient(app) as client:
        yield client, cfg, app


def test_info_and_cameras(setup):
    client, _, _ = setup
    info = client.get("/api/info").json()
    assert {"loitering", "intrusion", "abandoned_object"} <= set(info["rules"])
    cams = client.get("/api/cameras").json()
    assert cams[0]["id"] == "cam1" and cams[0]["status"]["state"] == "stopped"


def test_save_camera_with_zone_and_rule_persists_to_yaml(setup):
    client, cfg, _ = setup
    body = {
        "id": "cam1",
        "name": "Entrada",
        "source": client.get("/api/cameras").json()[0]["source"],
        "zones": [{"name": "frente", "kind": "loitering", "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], "schedules": []}],
        "rules": {"loitering": {"zones": ["frente"], "dwell_seconds": 1}},
    }
    r = client.put("/api/cameras/cam1", json=body)
    assert r.status_code == 200, r.text
    saved = yaml.safe_load(cfg.read_text(encoding="utf-8"))["cameras"][0]
    assert saved["name"] == "Entrada"
    assert saved["zones"][0]["name"] == "frente" and "schedules" not in saved["zones"][0]
    assert saved["rules"]["loitering"]["dwell_seconds"] == 1
    assert (cfg.parent / "config.yaml.bak").exists()


def test_invalid_change_is_rejected_and_file_untouched(setup):
    client, cfg, _ = setup
    before = cfg.read_text(encoding="utf-8")
    body = {"id": "cam1", "source": "x.mp4", "zones": [], "rules": {"loitering": {"zones": ["no_existe"]}}}
    r = client.put("/api/cameras/cam1", json=body)
    assert r.status_code == 422 and "zonas inexistentes" in r.json()["detail"]
    assert cfg.read_text(encoding="utf-8") == before


def test_add_and_delete_camera(setup):
    client, _, _ = setup
    assert client.put("/api/cameras/cam2", json={"id": "cam2", "source": "rtsp://x/1"}).status_code == 200
    assert [c["id"] for c in client.get("/api/cameras").json()] == ["cam1", "cam2"]
    assert client.delete("/api/cameras/cam2").json() == {"ok": True}
    assert client.delete("/api/cameras/cam1").status_code == 422  # debe quedar al menos una


def test_raw_frame_for_zone_editor(setup):
    client, _, _ = setup
    r = client.get("/api/cameras/cam1/frame.jpg?raw=true")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (120, 160)


def test_start_live_stream_alert_and_stop(setup):
    client, _, app = setup
    body = {
        "id": "cam1",
        "source": client.get("/api/cameras").json()[0]["source"],
        "zones": [{"name": "todo", "kind": "loitering", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        "rules": {"loitering": {"zones": ["todo"], "dwell_seconds": 0.5}},
    }
    assert client.put("/api/cameras/cam1", json=body).status_code == 200
    assert client.post("/api/cameras/cam1/start").json()["state"] in ("starting", "running")

    runner = app.state.runner
    deadline = time.time() + 10
    while runner.latest_jpeg("cam1") is None and time.time() < deadline:
        time.sleep(0.05)
    assert runner.latest_jpeg("cam1") is not None
    assert next(runner.frames("cam1"))[:2] == b"\xff\xd8"  # JPEG

    while not client.get("/events").json() and time.time() < deadline:
        time.sleep(0.05)
    events = client.get("/events").json()
    assert events and events[0]["rule"] == "loitering"

    client.post("/api/cameras/cam1/stop")
    assert client.get("/api/cameras").json()[0]["status"]["state"] in ("finished", "stopped")
