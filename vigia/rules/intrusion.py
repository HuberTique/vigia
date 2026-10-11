"""Intrusión por puertas, ventanas y zonas restringidas.

- Puertas y ventanas (``kind: door | window``): alerta sólo si una persona
  *entra* por ellas, es decir, aparece por primera vez dentro de la zona y
  luego avanza hacia el interior. Quien pasa por delante, o sale por la
  puerta, no genera alerta.
- Zonas restringidas (``kind: restricted``): alerta si una persona permanece
  dentro, sin importar por dónde llegó.
"""

from __future__ import annotations

from dataclasses import dataclass

from vigia.rules.base import Rule
from vigia.types import Event, FrameContext, TrackedObject
from vigia.zones import Zone

_LABEL = {"window": "ventana", "door": "puerta", "restricted": "zona restringida"}
_ENTRY_KINDS = ("door", "window")


@dataclass
class _Track:
    born_t: float
    born_xy: tuple[float, float]  # normalizado 0..1
    born_in: set[str]  # zonas de entrada donde apareció
    last_t: float
    outside_since: dict[str, float | None]
    alerted: set[str]


class IntrusionRule(Rule):
    """Parámetros (por regla o por zona):
    - confirm_seconds: tiempo continuo que debe cumplirse la condición antes de
      alertar, para descartar cuadros sueltos (por defecto 1.0).
    - birth_seconds: ventana desde que se ve a una persona por primera vez en
      la que debe estar dentro de la puerta/ventana para contar como que "salió
      de ahí" (por defecto 1.5).
    - min_travel: distancia mínima recorrida desde la puerta/ventana hacia el
      interior, como fracción del ancho de la imagen (por defecto 0.08).
    - sill_tolerance: en ventanas, cuánto pueden estar los pies por debajo del
      borde inferior de la zona, como fracción del alto de la imagen (0.1).
    - grace_seconds: en zonas restringidas, ausencia tolerada antes de reiniciar (2).

    La zona sólo vigila durante sus horarios (``schedules``); sin horario vigila siempre.
    """

    name = "intrusion"

    def __init__(self, zones=None, **params):
        super().__init__(zones, **params)
        self._tracks: dict[int, _Track] = {}
        self._presence: dict[tuple[str, int], list] = {}  # zonas restringidas: [first_t, last_t, alerted]

    def _inside(self, person: TrackedObject, zone: Zone, ctx: FrameContext) -> bool:
        if zone.kind != "window":
            return zone.contains(*person.anchor, ctx.width, ctx.height)
        # Ventanas: el cuerpo debe estar en el marco y los pies a la altura del
        # alféizar o más arriba. Así, alguien que camina por el piso delante de
        # la ventana no cuenta como que está "en" la ventana.
        if not zone.contains(*person.center, ctx.width, ctx.height):
            return False
        sill_y = max(y for _, y in zone.polygon) + float(self.param("sill_tolerance", 0.1, zone))
        return person.anchor[1] / ctx.height <= sill_y

    def update(self, ctx: FrameContext) -> list[Event]:
        events: list[Event] = []
        entry_zones = [z for z in self.zones if z.kind in _ENTRY_KINDS]
        presence_zones = [z for z in self.zones if z.kind not in _ENTRY_KINDS]

        for person in ctx.of_class("person"):
            events += self._update_entries(ctx, person, entry_zones)
            events += self._update_presence(ctx, person, presence_zones)

        self._tracks = {k: s for k, s in self._tracks.items() if ctx.t - s.last_t <= 10}
        self._presence = {k: s for k, s in self._presence.items() if ctx.t - s[1] <= 10}
        return events

    def _update_entries(self, ctx: FrameContext, person: TrackedObject, zones: list[Zone]) -> list[Event]:
        if not zones:
            return []
        ax, ay = person.anchor
        tr = self._tracks.get(person.track_id)
        if tr is None:
            tr = self._tracks[person.track_id] = _Track(
                born_t=ctx.t,
                born_xy=(ax / ctx.width, ay / ctx.height),
                born_in=set(),
                last_t=ctx.t,
                outside_since={},
                alerted=set(),
            )
        tr.last_t = ctx.t

        events = []
        for zone in zones:
            inside = self._inside(person, zone, ctx)
            birth_s = float(self.param("birth_seconds", 1.5, zone))
            if inside and ctx.t - tr.born_t <= birth_s:
                tr.born_in.add(zone.name)
            if zone.name not in tr.born_in or zone.name in tr.alerted or not zone.active(ctx.now):
                continue

            if inside:
                tr.outside_since[zone.name] = None
                continue
            if tr.outside_since.get(zone.name) is None:
                tr.outside_since[zone.name] = ctx.t

            travel = ((ax / ctx.width - tr.born_xy[0]) ** 2 + (ay / ctx.height - tr.born_xy[1]) ** 2) ** 0.5
            confirm_s = float(self.param("confirm_seconds", 1.0, zone))
            min_travel = float(self.param("min_travel", 0.08, zone))
            if ctx.t - tr.outside_since[zone.name] >= confirm_s and travel >= min_travel:
                tr.alerted.add(zone.name)
                label = _LABEL.get(zone.kind, zone.kind)
                events.append(
                    Event(
                        camera_id=ctx.camera_id,
                        rule=self.name,
                        t=ctx.t,
                        now=ctx.now,
                        zone=zone.name,
                        severity="high",
                        track_ids=[person.track_id],
                        bbox=(person.x1, person.y1, person.x2, person.y2),
                        message=f"Persona #{person.track_id} entró por {label} '{zone.name}' a las {ctx.now:%H:%M}",
                    )
                )
        return events

    def _update_presence(self, ctx: FrameContext, person: TrackedObject, zones: list[Zone]) -> list[Event]:
        events = []
        for zone in zones:
            if not zone.active(ctx.now) or not self._inside(person, zone, ctx):
                continue
            confirm_s = float(self.param("confirm_seconds", 1.0, zone))
            grace_s = float(self.param("grace_seconds", 2, zone))
            key = (zone.name, person.track_id)
            state = self._presence.get(key)
            if state is None or ctx.t - state[1] > grace_s:
                state = self._presence[key] = [ctx.t, ctx.t, False]
            state[1] = ctx.t
            if not state[2] and ctx.t - state[0] >= confirm_s:
                state[2] = True
                events.append(
                    Event(
                        camera_id=ctx.camera_id,
                        rule=self.name,
                        t=ctx.t,
                        now=ctx.now,
                        zone=zone.name,
                        severity="high",
                        track_ids=[person.track_id],
                        bbox=(person.x1, person.y1, person.x2, person.y2),
                        message=f"Persona #{person.track_id} dentro de {_LABEL['restricted']} '{zone.name}' a las {ctx.now:%H:%M}",
                    )
                )
        return events
