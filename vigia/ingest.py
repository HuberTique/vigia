"""Lectura de video: archivos locales o streams RTSP/HTTP de cámaras y NVR."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import cv2
import numpy as np

log = logging.getLogger(__name__)

_LIVE_PREFIXES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://")


@dataclass
class Frame:
    image: np.ndarray
    t: float  # segundos desde el inicio
    now: datetime  # hora "de pared" del cuadro


def is_live(source: str) -> bool:
    return source.startswith(_LIVE_PREFIXES) or source.isdigit()


class VideoSource:
    """Entrega cuadros a ``analysis_fps``.

    - Archivo: recorre el video saltando cuadros; el tiempo sale del número de
      cuadro, así los resultados son reproducibles. ``start_time`` permite
      simular que el video se grabó, por ejemplo, a las 23:00.
    - Stream en vivo: un hilo lee continuamente y guarda sólo el último cuadro
      (si el análisis va lento, se descartan cuadros en vez de acumular retraso).
      Si la cámara se cae, reconecta con espera creciente.
    """

    def __init__(self, source: str, analysis_fps: float, start_time: datetime | None = None, loop: bool = False):
        self.source = source
        self.analysis_fps = analysis_fps
        self.start_time = start_time
        self.loop = loop

    def frames(self) -> Iterator[Frame]:
        if is_live(self.source):
            yield from self._live()
        else:
            yield from self._file()

    def _file(self) -> Iterator[Frame]:
        start = self.start_time or datetime.now()
        offset = 0.0
        while True:
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                raise FileNotFoundError(f"No se pudo abrir el video {self.source}")
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            step = max(1, round(src_fps / self.analysis_fps))
            idx = 0
            last_t = 0.0
            while True:
                ok = cap.grab()
                if not ok:
                    break
                if idx % step == 0:
                    ok, img = cap.retrieve()
                    if ok:
                        last_t = offset + idx / src_fps
                        yield Frame(img, last_t, start + timedelta(seconds=last_t))
                idx += 1
            cap.release()
            if not self.loop:
                return
            offset = last_t + 1 / src_fps

    def _live(self) -> Iterator[Frame]:
        latest: dict = {"img": None, "seq": 0}
        stop = threading.Event()
        cond = threading.Condition()

        def reader():
            backoff = 1.0
            src = int(self.source) if self.source.isdigit() else self.source
            while not stop.is_set():
                cap = cv2.VideoCapture(src)
                if not cap.isOpened():
                    log.warning("No se pudo conectar a %s; reintento en %.0f s", self.source, backoff)
                    stop.wait(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                log.info("Conectado a %s", self.source)
                backoff = 1.0
                while not stop.is_set():
                    ok, img = cap.read()
                    if not ok:
                        log.warning("Se perdió el stream %s; reconectando", self.source)
                        break
                    with cond:
                        latest["img"] = img
                        latest["seq"] += 1
                        cond.notify_all()
                cap.release()

        th = threading.Thread(target=reader, daemon=True, name=f"ingest-{self.source}")
        th.start()
        t0 = time.monotonic()
        period = 1.0 / self.analysis_fps
        seen = 0
        try:
            while True:
                tick = time.monotonic()
                with cond:
                    cond.wait_for(lambda s=seen: latest["seq"] != s, timeout=5)
                    if latest["seq"] == seen:
                        continue
                    seen = latest["seq"]
                    img = latest["img"]
                yield Frame(img, time.monotonic() - t0, datetime.now())
                time.sleep(max(0.0, period - (time.monotonic() - tick)))
        finally:
            stop.set()
