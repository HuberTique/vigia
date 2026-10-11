"""API HTTP e interfaz web de Vigia.

- Sin archivo de configuración: sólo eventos (consulta y revisión).
- Con archivo de configuración: además cámaras, zonas, reglas, inicio/parada
  del análisis y video en vivo. Es lo que usa la interfaz (``vigia ui``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from vigia.events import EventStore


class Review(BaseModel):
    review: str | None  # valid | false_alarm | null


class ZoneIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "restricted"
    polygon: list[tuple[float, float]]
    schedules: list[str] = []
    params: dict = {}


class CameraIn(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = ""
    source: str = Field(min_length=1)
    zones: list[ZoneIn] | None = None
    rules: dict[str, dict] | None = None


def _index_html() -> str:
    return resources.files("vigia").joinpath("web/index.html").read_text(encoding="utf-8")


def create_app(data_dir: str, config_path: str | None = None, notifiers: list | None = None, preload_model: bool = False) -> FastAPI:
    store = EventStore(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        runner = getattr(app.state, "runner", None)
        if runner is not None:
            runner.stop_all()

    app = FastAPI(title="Vigia", description="Detección de riesgos en cámaras de seguridad", lifespan=lifespan)

    # ---------------- eventos ----------------

    @app.get("/events")
    def list_events(limit: int = 100, camera_id: str | None = None, rule: str | None = None):
        return store.list(limit=limit, camera_id=camera_id, rule=rule)

    @app.get("/events/{event_id}")
    def get_event(event_id: int):
        ev = store.get(event_id)
        if not ev:
            raise HTTPException(404, "Evento no encontrado")
        return ev

    @app.post("/events/{event_id}/review")
    def review_event(event_id: int, body: Review):
        try:
            ok = store.set_review(event_id, body.review)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if not ok:
            raise HTTPException(404, "Evento no encontrado")
        return store.get(event_id)

    def _media(event_id: int, field: str) -> FileResponse:
        ev = store.get(event_id)
        if not ev or not ev.get(field) or not Path(ev[field]).exists():
            raise HTTPException(404, "Archivo no disponible")
        return FileResponse(ev[field])

    @app.get("/events/{event_id}/snapshot")
    def snapshot(event_id: int):
        return _media(event_id, "snapshot_path")

    @app.get("/events/{event_id}/clip")
    def clip(event_id: int):
        return _media(event_id, "clip_path")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _index_html()

    if config_path is None:
        return app

    # ---------------- cámaras (requiere configuración) ----------------

    from vigia.config_store import ConfigError, ConfigStore
    from vigia.ingest import VideoSource
    from vigia.rules import RULE_INFO
    from vigia.runner import CameraRunner

    config = ConfigStore(config_path)
    runner = CameraRunner(config, store, notifiers)
    if preload_model:
        runner.preload_model()
    app.state.runner = runner
    app.state.config = config

    def _camera_out(raw: dict) -> dict:
        cam_id = str(raw["id"])
        return {
            "id": cam_id,
            "name": raw.get("name", ""),
            "source": raw.get("source", ""),
            "zones": raw.get("zones", []),
            "rules": raw.get("rules", {}),
            "status": runner.status(cam_id),
        }

    def _raw_or_404(cam_id: str) -> dict:
        try:
            return config.camera_raw(cam_id)
        except KeyError:
            raise HTTPException(404, f"No existe la cámara {cam_id}") from None

    @app.get("/api/info")
    def info():
        m = config.app.model
        return {
            "config_path": str(config.path),
            "model": {"backend": m.backend, "weights": m.weights, "classes": m.classes},
            "analysis_fps": config.app.analysis_fps,
            "rules": {
                name: {
                    "label": i["label"],
                    "zone_kinds": i["zone_kinds"],
                    "params": {k: {"default": d, "help": h} for k, (d, h) in i["params"].items()},
                }
                for name, i in RULE_INFO.items()
            },
            "zone_kinds": {
                "loitering": "Merodeo",
                "door": "Puerta",
                "window": "Ventana",
                "restricted": "Zona restringida",
            },
        }

    @app.get("/api/cameras")
    def cameras():
        return [_camera_out(c) for c in config.raw.get("cameras", [])]

    @app.put("/api/cameras/{cam_id}")
    def save_camera(cam_id: str, body: CameraIn):
        if body.id != cam_id:
            raise HTTPException(422, "El id del cuerpo no coincide con la URL")
        data = body.model_dump()
        if body.zones is not None:
            data["zones"] = [
                {k: v for k, v in z.model_dump().items() if v not in ([], {}, None)} | {"polygon": [list(p) for p in z.polygon]}
                for z in body.zones
            ]
        try:
            config.upsert_camera(data)
        except ConfigError as e:
            raise HTTPException(422, str(e)) from e
        runner.restart_if_running(cam_id)
        return _camera_out(config.camera_raw(cam_id))

    @app.delete("/api/cameras/{cam_id}")
    def delete_camera(cam_id: str):
        _raw_or_404(cam_id)
        runner.stop(cam_id)
        try:
            config.delete_camera(cam_id)
        except ConfigError as e:
            raise HTTPException(422, str(e)) from e
        return {"ok": True}

    @app.post("/api/cameras/{cam_id}/start")
    def start(cam_id: str):
        _raw_or_404(cam_id)
        runner.start(cam_id)
        return runner.status(cam_id)

    @app.post("/api/cameras/{cam_id}/stop")
    def stop(cam_id: str):
        _raw_or_404(cam_id)
        runner.stop(cam_id)
        return runner.status(cam_id)

    @app.get("/api/cameras/{cam_id}/frame.jpg")
    def frame(cam_id: str, raw: bool = False):
        """Un cuadro de la cámara. ``raw=true`` lo toma directo de la fuente, sin
        dibujos (para el editor de zonas)."""
        import cv2

        cam = _raw_or_404(cam_id)
        if not raw:
            jpeg = runner.latest_jpeg(cam_id)
            if jpeg:
                return Response(jpeg, media_type="image/jpeg")
        try:
            first = next(VideoSource(str(cam["source"]), config.app.analysis_fps).frames())
        except (StopIteration, FileNotFoundError, OSError) as e:
            raise HTTPException(502, f"No se pudo leer la fuente: {e}") from e
        ok, buf = cv2.imencode(".jpg", first.image)
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.get("/api/cameras/{cam_id}/stream.mjpg")
    def stream(cam_id: str):
        _raw_or_404(cam_id)

        def gen():
            for jpeg in runner.frames(cam_id):
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app
