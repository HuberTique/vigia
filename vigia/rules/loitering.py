"""Merodeo: una persona permanece demasiado tiempo dentro de una zona vigilada."""

from __future__ import annotations

from dataclasses import dataclass

from vigia.rules.base import Rule
from vigia.types import Event, FrameContext


@dataclass
class _Dwell:
    entered_at: float
    last_seen: float
    alerted: bool = False


class LoiteringRule(Rule):
    """Parámetros (por regla o por zona):
    - dwell_seconds: tiempo dentro de la zona para alertar (por defecto 60).
    - grace_seconds: ausencia tolerada antes de reiniciar el conteo, cubre
      oclusiones breves o parpadeos del detector (por defecto 3).
    """

    name = "loitering"

    def __init__(self, zones=None, **params):
        super().__init__(zones, **params)
        self._dwell: dict[tuple[str, int], _Dwell] = {}

    def update(self, ctx: FrameContext) -> list[Event]:
        events: list[Event] = []
        for zone in self.zones:
            if not zone.active(ctx.now):
                continue
            dwell_s = float(self.param("dwell_seconds", 60, zone))
            grace_s = float(self.param("grace_seconds", 3, zone))

            for person in ctx.of_class("person"):
                if not zone.contains(*person.anchor, ctx.width, ctx.height):
                    continue
                key = (zone.name, person.track_id)
                d = self._dwell.get(key)
                if d is None or ctx.t - d.last_seen > grace_s:
                    d = self._dwell[key] = _Dwell(entered_at=ctx.t, last_seen=ctx.t)
                d.last_seen = ctx.t
                if not d.alerted and ctx.t - d.entered_at >= dwell_s:
                    d.alerted = True
                    events.append(
                        Event(
                            camera_id=ctx.camera_id,
                            rule=self.name,
                            t=ctx.t,
                            now=ctx.now,
                            zone=zone.name,
                            severity="medium",
                            track_ids=[person.track_id],
                            bbox=(person.x1, person.y1, person.x2, person.y2),
                            message=f"Persona #{person.track_id} lleva {ctx.t - d.entered_at:.0f} s en la zona '{zone.name}'",
                        )
                    )

        # Olvidar a quien ya salió hace rato para que el estado no crezca sin límite.
        max_grace = max((float(self.param("grace_seconds", 3, z)) for z in self.zones), default=3)
        self._dwell = {k: d for k, d in self._dwell.items() if ctx.t - d.last_seen <= max_grace}
        return events
