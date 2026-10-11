"""Detectores intercambiables detrás de una misma interfaz.

Todos devuelven ``supervision.Detections`` con ``data["class_name"]`` lleno,
así el resto del sistema no sabe qué modelo hay debajo. Cambiar de YOLO26 a
RF-DETR es cambiar ``model.backend`` en la configuración.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import supervision as sv

from vigia.config import ModelConfig


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> sv.Detections: ...


def _keep_classes(det: sv.Detections, names: np.ndarray, wanted: set[str]) -> sv.Detections:
    det.data["class_name"] = names
    if wanted:
        det = det[np.isin(names, list(wanted))]
    return det


class UltralyticsDetector:
    """YOLO26 / YOLO11 / YOLOE de Ultralytics (licencia AGPL-3.0)."""

    def __init__(self, cfg: ModelConfig):
        from ultralytics import YOLO

        self.cfg = cfg
        self.model = YOLO(cfg.weights)
        self.wanted = set(cfg.classes)
        name_to_id = {v: k for k, v in self.model.names.items()}
        unknown = self.wanted - set(name_to_id)
        if unknown:
            raise ValueError(f"El modelo {cfg.weights} no conoce las clases {sorted(unknown)}")
        self.class_ids = [name_to_id[n] for n in self.wanted]

    def detect(self, frame: np.ndarray) -> sv.Detections:
        result = self.model.predict(
            frame,
            conf=self.cfg.confidence,
            classes=self.class_ids,
            imgsz=self.cfg.imgsz,
            device=self.cfg.device,
            verbose=False,
        )[0]
        det = sv.Detections.from_ultralytics(result)
        names = np.array([self.model.names[int(c)] for c in det.class_id], dtype=object)
        return _keep_classes(det, names, self.wanted)


class RFDETRDetector:
    """RF-DETR de Roboflow (Apache 2.0 en tamaños nano a large). ``weights`` es el
    tamaño: nano | small | medium | large, o la ruta a un checkpoint afinado."""

    SIZES = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "large": "RFDETRLarge"}

    def __init__(self, cfg: ModelConfig):
        import rfdetr

        self.cfg = cfg
        self.wanted = set(cfg.classes)
        if cfg.weights in self.SIZES:
            self.model = getattr(rfdetr, self.SIZES[cfg.weights])()
        else:
            self.model = rfdetr.RFDETRNano(pretrain_weights=cfg.weights)

    def detect(self, frame: np.ndarray) -> sv.Detections:
        # RF-DETR espera RGB; OpenCV entrega BGR.
        det = self.model.predict(frame[:, :, ::-1].copy(), threshold=self.cfg.confidence)
        # RF-DETR ya entrega el nombre de cada clase (sus IDs siguen la numeración
        # COCO original, que no coincide con el índice de la lista de nombres).
        names = np.asarray(det.data.get("class_name", []), dtype=object)
        return _keep_classes(det, names, self.wanted)


def build_detector(cfg: ModelConfig) -> Detector:
    backends = {"ultralytics": UltralyticsDetector, "rfdetr": RFDETRDetector}
    if cfg.backend not in backends:
        raise ValueError(f"backend desconocido '{cfg.backend}'. Opciones: {sorted(backends)}")
    return backends[cfg.backend](cfg)
