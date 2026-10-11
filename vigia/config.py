"""Carga de configuración desde YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vigia.rules import REGISTRY, Rule
from vigia.zones import Schedule, Zone


@dataclass
class ModelConfig:
    backend: str = "ultralytics"  # ultralytics | rfdetr
    weights: str = "yolo26n.pt"
    confidence: float = 0.35
    classes: list[str] = field(default_factory=lambda: ["person", "backpack", "handbag", "suitcase"])
    device: str | None = None
    imgsz: int = 640


@dataclass
class CameraConfig:
    id: str
    source: str
    name: str = ""
    zones: list[Zone] = field(default_factory=list)
    rules: dict[str, dict] = field(default_factory=dict)

    def build_rules(self) -> list[Rule]:
        by_name = {z.name: z for z in self.zones}
        built = []
        for rule_name, params in self.rules.items():
            if rule_name not in REGISTRY:
                raise ValueError(f"Cámara {self.id}: regla desconocida '{rule_name}'. Disponibles: {sorted(REGISTRY)}")
            params = dict(params or {})
            if params.pop("enabled", True) is False:
                continue
            zone_names = params.pop("zones", None)
            if zone_names is None:
                zones = []
            else:
                missing = [n for n in zone_names if n not in by_name]
                if missing:
                    raise ValueError(f"Cámara {self.id}, regla {rule_name}: zonas inexistentes {missing}")
                zones = [by_name[n] for n in zone_names]
            built.append(REGISTRY[rule_name](zones=zones, **params))
        return built


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"


@dataclass
class AppConfig:
    cameras: list[CameraConfig]
    model: ModelConfig = field(default_factory=ModelConfig)
    analysis_fps: float = 5.0
    data_dir: str = "data"
    clip_pre_seconds: float = 5.0
    clip_post_seconds: float = 5.0
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


def _zone(d: dict) -> Zone:
    poly = [tuple(map(float, p)) for p in d["polygon"]]
    if len(poly) < 3:
        raise ValueError(f"La zona '{d['name']}' necesita al menos 3 puntos")
    for x, y in poly:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"La zona '{d['name']}' usa coordenadas fuera de 0..1 (deben ser normalizadas)")
    return Zone(
        name=d["name"],
        kind=d.get("kind", "restricted"),
        polygon=poly,
        schedules=[Schedule.parse(s) for s in d.get("schedules", [])],
        params=d.get("params", {}),
    )


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cams = [
        CameraConfig(
            id=str(c["id"]),
            source=str(c["source"]),
            name=c.get("name", ""),
            zones=[_zone(z) for z in c.get("zones", [])],
            rules=c.get("rules", {}),
        )
        for c in raw.get("cameras", [])
    ]
    if not cams:
        raise ValueError("La configuración no tiene cámaras")
    clips = raw.get("clips", {})
    return AppConfig(
        cameras=cams,
        model=ModelConfig(**raw.get("model", {})),
        analysis_fps=float(raw.get("analysis_fps", 5)),
        data_dir=raw.get("data_dir", "data"),
        clip_pre_seconds=float(clips.get("pre_seconds", 5)),
        clip_post_seconds=float(clips.get("post_seconds", 5)),
        telegram=TelegramConfig(**raw.get("notify", {}).get("telegram", {})),
    )
