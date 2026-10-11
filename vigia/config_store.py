"""Lectura y escritura del archivo de configuración desde la interfaz.

Trabaja sobre el YAML "crudo" (diccionarios) y valida cada cambio con
``load_config`` antes de guardarlo, para que la interfaz nunca deje un archivo
que luego no arranque. Antes de sobrescribir guarda una copia ``.bak``.
"""

from __future__ import annotations

import copy
import shutil
import tempfile
import threading
from pathlib import Path

import yaml

from vigia.config import AppConfig, load_config


class ConfigError(ValueError):
    pass


class ConfigStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.raw: dict = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.app: AppConfig = load_config(self.path)

    def camera_raw(self, cam_id: str) -> dict:
        for c in self.raw.get("cameras", []):
            if str(c.get("id")) == cam_id:
                return c
        raise KeyError(cam_id)

    def _commit(self, new_raw: dict) -> None:
        """Valida ``new_raw`` y, si es correcto, lo guarda en disco."""
        text = yaml.safe_dump(new_raw, sort_keys=False, allow_unicode=True, default_flow_style=None)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
            tmp.write(text)
        try:
            app = load_config(tmp.name)
            for cam in app.cameras:
                cam.build_rules()  # detecta zonas o reglas inválidas
        except (ValueError, KeyError, TypeError) as e:
            raise ConfigError(str(e)) from e
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        shutil.copyfile(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        self.path.write_text(text, encoding="utf-8")
        self.raw, self.app = new_raw, app

    def upsert_camera(self, cam: dict) -> None:
        with self._lock:
            raw = copy.deepcopy(self.raw)
            cams = raw.setdefault("cameras", [])
            cam = {k: v for k, v in cam.items() if v is not None}
            cam["id"] = str(cam["id"])
            for i, c in enumerate(cams):
                if str(c.get("id")) == cam["id"]:
                    cams[i] = {**c, **cam}
                    break
            else:
                cam.setdefault("zones", [])
                cam.setdefault("rules", {})
                cams.append(cam)
            self._commit(raw)

    def delete_camera(self, cam_id: str) -> None:
        with self._lock:
            raw = copy.deepcopy(self.raw)
            cams = raw.get("cameras", [])
            remaining = [c for c in cams if str(c.get("id")) != cam_id]
            if len(remaining) == len(cams):
                raise KeyError(cam_id)
            if not remaining:
                raise ConfigError("Debe quedar al menos una cámara")
            raw["cameras"] = remaining
            self._commit(raw)
