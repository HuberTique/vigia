"""Zonas poligonales y horarios.

Las zonas se definen en coordenadas normalizadas (0 a 1) para que sirvan con
cualquier resolución de la cámara, y se convierten a píxeles al usarlas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray casting. El polígono se da como lista de vértices (x, y)."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@dataclass(frozen=True)
class Schedule:
    """Franja horaria activa, por ejemplo 22:00-06:00 (puede cruzar la medianoche)."""

    start: time
    end: time

    @classmethod
    def parse(cls, text: str) -> Schedule:
        a, b = (s.strip() for s in text.split("-"))
        return cls(time.fromisoformat(a), time.fromisoformat(b))

    def active(self, now: datetime) -> bool:
        t = now.time()
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


@dataclass
class Zone:
    name: str
    kind: str  # loitering | restricted | window | door
    polygon: list[tuple[float, float]]  # normalizado 0..1
    schedules: list[Schedule] = field(default_factory=list)  # vacío = siempre activa
    params: dict = field(default_factory=dict)  # umbrales propios de la zona

    def active(self, now: datetime) -> bool:
        return not self.schedules or any(s.active(now) for s in self.schedules)

    def contains(self, x: float, y: float, width: int, height: int) -> bool:
        return point_in_polygon(x / width, y / height, self.polygon)

    def pixel_polygon(self, width: int, height: int) -> list[tuple[int, int]]:
        return [(round(x * width), round(y * height)) for x, y in self.polygon]
