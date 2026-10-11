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

__all__ = ["REGISTRY", "Rule", "LoiteringRule", "IntrusionRule", "AbandonedObjectRule"]
