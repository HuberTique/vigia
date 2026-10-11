"""Bucle de análisis por cámara: ingesta → detección → tracking → reglas → eventos."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

import cv2
import numpy as np
import supervision as sv

from vigia.config import AppConfig, CameraConfig
from vigia.events import ClipRecorder, EventStore, save_snapshot
from vigia.ingest import VideoSource
from vigia.perception.detector import Detector
from vigia.perception.tracker import Tracker
from vigia.types import Event, FrameContext

log = logging.getLogger(__name__)

_ZONE_COLORS = {
    "loitering": (0, 200, 255),
    "restricted": (0, 0, 255),
    "door": (255, 0, 255),
    "window": (255, 128, 0),
}


class CameraPipeline:
    def __init__(
        self,
        app: AppConfig,
        cam: CameraConfig,
        detector: Detector,
        store: EventStore,
        notifiers: list | None = None,
        detector_lock: threading.Lock | None = None,
        start_time: datetime | None = None,
        loop: bool = False,
        save_video: str | None = None,
    ):
        self.app = app
        self.cam = cam
        self.detector = detector
        self.store = store
        self.notifiers = notifiers or []
        self.lock = detector_lock or threading.Lock()
        self.source = VideoSource(cam.source, app.analysis_fps, start_time=start_time, loop=loop)
        self.tracker = Tracker(app.analysis_fps)
        self.rules = cam.build_rules()
        self.clips = ClipRecorder(store, app.analysis_fps, app.clip_pre_seconds, app.clip_post_seconds)
        self.save_video = save_video
        self.events: list[Event] = []
        self.error: BaseException | None = None
        self._box = sv.BoxAnnotator(thickness=2)
        self._label = sv.LabelAnnotator(text_scale=0.5, text_padding=3)

    def run(self, max_seconds: float | None = None) -> list[Event]:
        try:
            return self._run(max_seconds)
        except Exception as e:
            self.error = e
            log.exception("La cámara %s se detuvo por un error", self.cam.id)
            raise

    def _run(self, max_seconds: float | None) -> list[Event]:
        writer = None
        try:
            for frame in self.source.frames():
                if max_seconds is not None and frame.t > max_seconds:
                    break
                img = frame.image
                h, w = img.shape[:2]
                with self.lock:
                    det = self.detector.detect(img)
                tracked, objects = self.tracker.update(det, frame.t)
                ctx = FrameContext(self.cam.id, frame.t, frame.now, w, h, objects)

                new_events: list[Event] = []
                for rule in self.rules:
                    new_events.extend(rule.update(ctx))

                annotated = self._annotate(img, tracked, new_events)
                for ev in new_events:
                    self._emit(ev, img)
                self.clips.push(annotated, frame.t)

                if self.save_video:
                    if writer is None:
                        writer = cv2.VideoWriter(self.save_video, cv2.VideoWriter_fourcc(*"mp4v"), self.app.analysis_fps, (w, h))
                    writer.write(annotated)
        finally:
            self.clips.flush()
            if writer is not None:
                writer.release()
        return self.events

    def _emit(self, ev: Event, frame: np.ndarray) -> None:
        self.store.add(ev)
        ev.snapshot_path = save_snapshot(self.store, frame, ev)
        self.clips.start(ev)
        self.events.append(ev)
        log.warning("[%s] %s: %s", ev.camera_id, ev.rule, ev.message)
        for n in self.notifiers:
            n.send(ev, ev.snapshot_path)

    def _annotate(self, img: np.ndarray, tracked: sv.Detections, events: list[Event]) -> np.ndarray:
        out = img.copy()
        h, w = out.shape[:2]
        for z in self.cam.zones:
            pts = np.array(z.pixel_polygon(w, h), dtype=np.int32)
            color = _ZONE_COLORS.get(z.kind, (200, 200, 200))
            cv2.polylines(out, [pts], True, color, 2)
            cv2.putText(out, z.name, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if len(tracked):
            labels = [f"#{t} {n}" for t, n in zip(tracked.tracker_id, tracked.data["class_name"], strict=True)]
            out = self._box.annotate(out, tracked)
            out = self._label.annotate(out, tracked, labels)
        for ev in events:
            if ev.bbox:
                x1, y1, x2, y2 = map(int, ev.bbox)
                cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 4)
        return out
