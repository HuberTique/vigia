"""Objeto abandonado: un bolso, mochila o maleta queda quieto y sin ninguna
persona cerca durante cierto tiempo.

No depende del ID del tracker para el objeto: cuando alguien pasa por delante,
el tracker suele perder y renombrar los objetos quietos. En su lugar, se
emparejan por posición (IoU) contra los candidatos conocidos.
"""

from __future__ import annotations

from dataclasses import dataclass

from vigia.rules.base import Rule
from vigia.types import Event, FrameContext, TrackedObject

DEFAULT_CLASSES = ("backpack", "handbag", "suitcase")


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])  # noqa: E731
    return inter / (area(a) + area(b) - inter)


@dataclass
class _Candidate:
    cid: int
    class_name: str
    bbox: tuple[float, float, float, float]
    first_seen: float
    last_seen: float
    unattended_since: float | None = None
    alerted: bool = False


class AbandonedObjectRule(Rule):
    """Parámetros:
    - classes: clases consideradas objetos (por defecto mochila, bolso, maleta).
    - static_seconds: tiempo quieto en el mismo lugar (por defecto 30).
    - unattended_seconds: tiempo sin nadie cerca (por defecto 20).
    - owner_radius: distancia máxima, en alturas del objeto, para considerar
      que una persona lo está cuidando (por defecto 4).
    - match_iou: IoU mínimo para decir que es el mismo objeto quieto (0.5).
    - forget_seconds: tiempo sin verlo para olvidarlo (por defecto 10).

    Si se configuran zonas, sólo vigila objetos dentro de ellas.
    """

    name = "abandoned_object"

    def __init__(self, zones=None, **params):
        super().__init__(zones, **params)
        self._candidates: list[_Candidate] = []
        self._next_id = 1

    def _match(self, obj: TrackedObject, iou_min: float) -> _Candidate | None:
        box = (obj.x1, obj.y1, obj.x2, obj.y2)
        best, best_iou = None, iou_min
        for c in self._candidates:
            v = _iou(c.bbox, box)
            if v >= best_iou:
                best, best_iou = c, v
        return best

    def update(self, ctx: FrameContext) -> list[Event]:
        classes = tuple(self.params.get("classes", DEFAULT_CLASSES))
        static_s = float(self.params.get("static_seconds", 30))
        unattended_s = float(self.params.get("unattended_seconds", 20))
        radius = float(self.params.get("owner_radius", 4))
        iou_min = float(self.params.get("match_iou", 0.5))
        forget_s = float(self.params.get("forget_seconds", 10))

        people = ctx.of_class("person")
        events: list[Event] = []
        for obj in ctx.of_class(*classes):
            zone = None
            if self.zones:
                zone = next(
                    (z for z in self.zones if z.active(ctx.now) and z.contains(*obj.anchor, ctx.width, ctx.height)),
                    None,
                )
                if zone is None:
                    continue
            c = self._match(obj, iou_min)
            if c is None:
                c = _Candidate(self._next_id, obj.class_name, (obj.x1, obj.y1, obj.x2, obj.y2), ctx.t, ctx.t)
                self._next_id += 1
                self._candidates.append(c)
            c.last_seen = ctx.t

            ox, oy = obj.center
            max_d = radius * max(obj.height, 1.0)
            attended = any(((p.anchor[0] - ox) ** 2 + (p.anchor[1] - oy) ** 2) ** 0.5 <= max_d for p in people)
            if attended:
                c.unattended_since = None
            elif c.unattended_since is None:
                c.unattended_since = ctx.t

            if (
                not c.alerted
                and ctx.t - c.first_seen >= static_s
                and c.unattended_since is not None
                and ctx.t - c.unattended_since >= unattended_s
            ):
                c.alerted = True
                events.append(
                    Event(
                        camera_id=ctx.camera_id,
                        rule=self.name,
                        t=ctx.t,
                        now=ctx.now,
                        zone=zone.name if zone else None,
                        severity="high",
                        bbox=c.bbox,
                        message=(
                            f"Objeto ({obj.class_name}) quieto hace {ctx.t - c.first_seen:.0f} s "
                            f"y sin nadie cerca hace {ctx.t - c.unattended_since:.0f} s"
                        ),
                    )
                )

        self._candidates = [c for c in self._candidates if ctx.t - c.last_seen <= forget_s]
        return events
