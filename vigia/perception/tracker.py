"""Seguimiento de objetos entre cuadros (ByteTrack del paquete ``trackers`` de Roboflow)."""

from __future__ import annotations

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

from vigia.types import TrackedObject


class Tracker:
    def __init__(self, fps: float, lost_seconds: float = 2.0, activation_threshold: float = 0.4):
        # Umbrales más bajos que los de fábrica: en CCTV las personas lejanas
        # suelen detectarse con confianza moderada.
        self._bt = ByteTrackTracker(
            frame_rate=fps,
            lost_track_buffer=max(1, round(lost_seconds * fps)),
            track_activation_threshold=activation_threshold,
            high_conf_det_threshold=max(activation_threshold, 0.5),
        )

    def update(self, det: sv.Detections, t: float | None = None) -> tuple[sv.Detections, list[TrackedObject]]:
        tracked = self._bt.update(det, timestamp=t)
        if len(tracked):
            tracked = tracked[tracked.tracker_id != -1]  # detecciones aún sin track confirmado
        if "class_name" not in tracked.data:
            tracked.data["class_name"] = np.array([], dtype=object)
        objects = [
            TrackedObject(
                track_id=int(tid),
                class_name=str(name),
                confidence=float(conf),
                x1=float(box[0]),
                y1=float(box[1]),
                x2=float(box[2]),
                y2=float(box[3]),
            )
            for box, tid, conf, name in zip(tracked.xyxy, tracked.tracker_id, tracked.confidence, tracked.data["class_name"], strict=True)
        ]
        return tracked, objects
