"""Arranca y detiene el análisis de cada cámara en segundo plano, para la interfaz."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from vigia.config_store import ConfigStore
from vigia.events import EventStore
from vigia.ingest import is_live
from vigia.pipeline import CameraPipeline

log = logging.getLogger(__name__)


@dataclass
class _Running:
    pipeline: CameraPipeline
    thread: threading.Thread
    started_at: float
    latest_jpeg: bytes | None = None
    frame_seq: int = 0
    first_frame_at: float | None = None
    cond: threading.Condition = field(default_factory=threading.Condition)


class CameraRunner:
    def __init__(self, config: ConfigStore, store: EventStore, notifiers: list | None = None):
        self.config = config
        self.store = store
        self.notifiers = notifiers or []
        self._detector = None
        self._detector_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._running: dict[str, _Running] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def _get_detector(self):
        # El modelo se carga una sola vez y lo comparten todas las cámaras.
        with self._load_lock:
            if self._detector is None:
                from vigia.perception.detector import build_detector

                self._detector = build_detector(self.config.app.model)
            return self._detector

    def preload_model(self) -> None:
        """Carga el modelo en segundo plano para que la primera cámara arranque rápido."""
        threading.Thread(target=self._get_detector, daemon=True, name="carga-modelo").start()

    def reload_model(self) -> None:
        with self._load_lock:
            self._detector = None

    def status(self, cam_id: str) -> dict:
        r = self._running.get(cam_id)
        if r and r.thread.is_alive():
            if r.first_frame_at is None:
                # Cargando el modelo o conectando con la cámara.
                return {"state": "starting", "events": len(r.pipeline.events)}
            elapsed = max(time.monotonic() - r.first_frame_at, 1e-6)
            return {
                "state": "running",
                "fps": round(r.pipeline.frames_processed / elapsed, 1),
                "events": len(r.pipeline.events),
            }
        if cam_id in self._errors:
            return {"state": "error", "error": self._errors[cam_id]}
        if r:
            return {"state": "finished", "events": len(r.pipeline.events)}
        return {"state": "stopped"}

    def start(self, cam_id: str) -> None:
        with self._lock:
            r = self._running.get(cam_id)
            if r and r.thread.is_alive() and not r.pipeline.stop_event.is_set():
                return  # ya está corriendo
            cam = next((c for c in self.config.app.cameras if c.id == cam_id), None)
            if cam is None:
                raise KeyError(cam_id)
            self._errors.pop(cam_id, None)
            holder: dict = {}

            def publish(img: np.ndarray) -> None:
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    run = holder["run"]
                    if run.first_frame_at is None:
                        run.first_frame_at = time.monotonic()
                    with run.cond:
                        run.latest_jpeg = buf.tobytes()
                        run.frame_seq += 1
                        run.cond.notify_all()

            def work() -> None:
                try:
                    pipeline = holder["run"].pipeline
                    pipeline.detector = self._get_detector()
                    pipeline.run()
                except Exception as e:  # el error se muestra en la interfaz
                    self._errors[cam_id] = str(e)

            # Los archivos se reproducen a velocidad real y en bucle, como si fueran una cámara.
            file_source = not is_live(cam.source)
            pipeline = CameraPipeline(
                self.config.app,
                cam,
                detector=None,  # se asigna en el hilo: cargar el modelo puede tardar
                store=self.store,
                notifiers=self.notifiers,
                detector_lock=self._detector_lock,
                loop=file_source,
                realtime=file_source,
                on_frame=publish,
            )
            thread = threading.Thread(target=work, daemon=True, name=f"cam-{cam_id}")
            holder["run"] = self._running[cam_id] = _Running(pipeline, thread, time.monotonic())
            thread.start()

    def stop(self, cam_id: str, wait: float = 5.0) -> None:
        r = self._running.get(cam_id)
        if r:
            r.pipeline.stop_event.set()
            r.thread.join(timeout=wait)

    def restart_if_running(self, cam_id: str) -> None:
        r = self._running.get(cam_id)
        if r and r.thread.is_alive() and not r.pipeline.stop_event.is_set():
            self.stop(cam_id)
            self.start(cam_id)

    def stop_all(self) -> None:
        for cam_id in list(self._running):
            self.stop(cam_id, wait=2)

    def latest_jpeg(self, cam_id: str) -> bytes | None:
        r = self._running.get(cam_id)
        return r.latest_jpeg if r else None

    def frames(self, cam_id: str):
        """Generador de cuadros JPEG nuevos para la transmisión MJPEG."""
        seen = -1
        while True:
            r = self._running.get(cam_id)
            if r is None or not r.thread.is_alive():
                return
            with r.cond:
                r.cond.wait_for(lambda run=r, s=seen: run.frame_seq != s, timeout=2)
                if r.frame_seq == seen or r.latest_jpeg is None:
                    continue
                seen, jpeg = r.frame_seq, r.latest_jpeg
            yield jpeg
