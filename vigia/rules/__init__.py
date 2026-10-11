from vigia.rules.abandoned import AbandonedObjectRule
from vigia.rules.base import Rule
from vigia.rules.intrusion import IntrusionRule
from vigia.rules.loitering import LoiteringRule

# Nombre en la configuración -> clase. Las reglas nuevas (escalamiento, peleas,
# armas) se registran aquí.
REGISTRY: dict[str, type[Rule]] = {
    LoiteringRule.name: LoiteringRule,
    IntrusionRule.name: IntrusionRule,
    AbandonedObjectRule.name: AbandonedObjectRule,
}

__all__ = ["REGISTRY", "RULE_INFO", "Rule", "LoiteringRule", "IntrusionRule", "AbandonedObjectRule"]

# Descripción de cada regla para la interfaz: etiqueta, tipos de zona que usa y
# parámetros editables (nombre -> (valor por defecto, descripción)).
RULE_INFO: dict[str, dict] = {
    "loitering": {
        "label": "Merodeo",
        "zone_kinds": ["loitering"],
        "params": {
            "dwell_seconds": (60, "Segundos dentro de la zona para alertar"),
            "grace_seconds": (3, "Segundos de ausencia tolerados (oclusiones)"),
        },
    },
    "intrusion": {
        "label": "Intrusión",
        "zone_kinds": ["door", "window", "restricted"],
        "params": {
            "confirm_seconds": (1.0, "Segundos para confirmar la entrada"),
            "min_travel": (0.08, "Distancia mínima hacia el interior (fracción del ancho)"),
            "birth_seconds": (1.5, "Segundos para considerar que la persona apareció en la puerta/ventana"),
        },
    },
    "abandoned_object": {
        "label": "Objeto abandonado",
        "zone_kinds": [],
        "params": {
            "static_seconds": (30, "Segundos quieto en el mismo lugar"),
            "unattended_seconds": (20, "Segundos sin nadie cerca"),
            "owner_radius": (4, "Distancia del dueño, en alturas del objeto"),
        },
    },
}
