"""Interfaz común de las reglas de riesgo."""

from __future__ import annotations

from abc import ABC, abstractmethod

from vigia.types import Event, FrameContext
from vigia.zones import Zone


class Rule(ABC):
    """Cada escenario de riesgo es una regla que recibe los objetos seguidos de
    un cuadro y devuelve los eventos nuevos. Mantiene su propio estado entre cuadros."""

    name: str = "rule"

    def __init__(self, zones: list[Zone] | None = None, **params):
        self.zones = zones or []
        self.params = params

    def param(self, key: str, default, zone: Zone | None = None):
        """Busca un umbral primero en la zona, luego en la regla, luego el valor por defecto."""
        if zone is not None and key in zone.params:
            return zone.params[key]
        return self.params.get(key, default)

    @abstractmethod
    def update(self, ctx: FrameContext) -> list[Event]: ...
