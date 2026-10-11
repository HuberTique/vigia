"""Intrusión: una persona entra a una zona restringida, una puerta fuera de
horario o una ventana (por una ventana nunca se entra legítimamente)."""

from __future__ import annotations

from vigia.rules.base import Rule
from vigia.types import Event, FrameContext

_SEVERITY = {"window": "high", "door": "high", "restricted": "high"}
_LABEL = {"window": "ventana", "door": "puerta", "restricted": "zona restringida"}


class IntrusionRule(Rule):
    """Parámetros (por regla o por zona):
    - confirm_seconds: tiempo continuo dentro de la zona para confirmar y evitar
      falsas alarmas por un cuadro suelto (por defecto 1.0).
    - grace_seconds: ausencia tolerada antes de reiniciar (por defecto 2).

    La zona sólo vigila durante sus horarios (``schedules``); sin horario vigila siempre.
    """

    name = "intrusion"

    def __init__(self, zones=None, **params):
        super().__init__(zones, **params)
        self._inside: dict[tuple[str, int], list] = {}  # key -> [first_t, last_t, alerted]

    def update(self, ctx: FrameContext) -> list[Event]:
        events: list[Event] = []
        for zone in self.zones:
            if not zone.active(ctx.now):
                continue
            confirm_s = float(self.param("confirm_seconds", 1.0, zone))
            grace_s = float(self.param("grace_seconds", 2, zone))
            for person in ctx.of_class("person"):
                # En ventanas la persona puede estar "colgada" del marco, así que
                # basta con que el centro del cuerpo esté dentro; en el resto, los pies.
                point = person.center if zone.kind == "window" else person.anchor
                if not zone.contains(*point, ctx.width, ctx.height):
                    continue
                key = (zone.name, person.track_id)
                state = self._inside.get(key)
                if state is None or ctx.t - state[1] > grace_s:
                    state = self._inside[key] = [ctx.t, ctx.t, False]
                state[1] = ctx.t
                if not state[2] and ctx.t - state[0] >= confirm_s:
                    state[2] = True
                    label = _LABEL.get(zone.kind, zone.kind)
                    events.append(
                        Event(
                            camera_id=ctx.camera_id,
                            rule=self.name,
                            t=ctx.t,
                            now=ctx.now,
                            zone=zone.name,
                            severity=_SEVERITY.get(zone.kind, "high"),
                            track_ids=[person.track_id],
                            bbox=(person.x1, person.y1, person.x2, person.y2),
                            message=f"Persona #{person.track_id} ingresó por {label} '{zone.name}' a las {ctx.now:%H:%M}",
                        )
                    )
        self._inside = {k: s for k, s in self._inside.items() if ctx.t - s[1] <= 10}
        return events
