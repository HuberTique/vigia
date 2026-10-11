"""Alertas por Telegram: envía la foto del evento con su descripción."""

from __future__ import annotations

import logging
import os

import requests

from vigia.config import TelegramConfig
from vigia.types import Event

log = logging.getLogger(__name__)

_ICON = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}


class TelegramNotifier:
    def __init__(self, cfg: TelegramConfig):
        self.token = os.environ.get(cfg.bot_token_env, "")
        self.chat_id = os.environ.get(cfg.chat_id_env, "")
        if not self.token or not self.chat_id:
            raise ValueError(f"Faltan las variables de entorno {cfg.bot_token_env} y/o {cfg.chat_id_env}")

    def send(self, ev: Event, snapshot_path: str | None) -> None:
        caption = f"{_ICON.get(ev.severity, '')} [{ev.camera_id}] {ev.message}"
        base = f"https://api.telegram.org/bot{self.token}"
        try:
            if snapshot_path:
                with open(snapshot_path, "rb") as f:
                    r = requests.post(
                        f"{base}/sendPhoto", data={"chat_id": self.chat_id, "caption": caption}, files={"photo": f}, timeout=15
                    )
            else:
                r = requests.post(f"{base}/sendMessage", data={"chat_id": self.chat_id, "text": caption}, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            # Una alerta perdida no debe tumbar el análisis de video.
            log.error("No se pudo enviar la alerta a Telegram: %s", e)
