"""Tipos compartidos entre percepción, reglas y eventos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TrackedObject:
    """Un objeto detectado y seguido en un cuadro, en coordenadas de píxeles."""

    track_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def anchor(self) -> tuple[float, float]:
        """Punto de apoyo (centro inferior de la caja): los pies de una persona o la base de un objeto."""
        return ((self.x1 + self.x2) / 2, self.y2)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def height(self) -> float:
        return self.y2 - self.y1


@dataclass
class FrameContext:
    """Lo que una regla recibe en cada cuadro analizado."""

    camera_id: str
    t: float  # segundos desde el inicio del stream (monótono)
    now: datetime  # hora local, para reglas con horario
    width: int
    height: int
    objects: list[TrackedObject]

    def of_class(self, *names: str) -> list[TrackedObject]:
        return [o for o in self.objects if o.class_name in names]


@dataclass
class Event:
    """Una alerta generada por una regla."""

    camera_id: str
    rule: str
    t: float
    now: datetime
    message: str
    severity: str = "medium"  # low | medium | high
    zone: str | None = None
    track_ids: list[int] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    id: int | None = None
    snapshot_path: str | None = None
    clip_path: str | None = None
