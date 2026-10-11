"""Persistencia de eventos: base SQLite, foto del momento y clip corto."""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from vigia.types import Event

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    zone TEXT,
    message TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    stream_t REAL NOT NULL,
    track_ids TEXT,
    snapshot_path TEXT,
    clip_path TEXT,
    review TEXT  -- NULL: sin revisar | valid | false_alarm
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(occurred_at);
"""


class EventStore:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        (self.dir / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.dir / "clips").mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "events.db"
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, ev: Event) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO events (camera_id, rule, severity, zone, message, occurred_at, stream_t, track_ids)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev.camera_id,
                    ev.rule,
                    ev.severity,
                    ev.zone,
                    ev.message,
                    ev.now.isoformat(timespec="seconds"),
                    ev.t,
                    ",".join(map(str, ev.track_ids)),
                ),
            )
            ev.id = cur.lastrowid
        return ev.id

    def set_media(self, event_id: int, snapshot: str | None = None, clip: str | None = None) -> None:
        with self._conn() as c:
            if snapshot:
                c.execute("UPDATE events SET snapshot_path=? WHERE id=?", (snapshot, event_id))
            if clip:
                c.execute("UPDATE events SET clip_path=? WHERE id=?", (clip, event_id))

    def set_review(self, event_id: int, review: str | None) -> bool:
        if review not in (None, "valid", "false_alarm"):
            raise ValueError("review debe ser valid, false_alarm o null")
        with self._conn() as c:
            return c.execute("UPDATE events SET review=? WHERE id=?", (review, event_id)).rowcount > 0

    def list(self, limit: int = 100, camera_id: str | None = None, rule: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM events WHERE 1=1", []
        if camera_id:
            q += " AND camera_id=?"
            args.append(camera_id)
        if rule:
            q += " AND rule=?"
            args.append(rule)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def get(self, event_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return dict(r) if r else None


def draw_event(frame: np.ndarray, ev: Event) -> np.ndarray:
    img = frame.copy()
    if ev.bbox:
        x1, y1, x2, y2 = map(int, ev.bbox)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
    label = f"{ev.rule} | {ev.now:%Y-%m-%d %H:%M:%S}"
    cv2.rectangle(img, (0, 0), (img.shape[1], 32), (0, 0, 0), -1)
    cv2.putText(img, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return img


@dataclass
class _PendingClip:
    event_id: int
    path: Path
    until_t: float
    frames: list[np.ndarray]


class ClipRecorder:
    """Guarda los últimos ``pre_seconds`` de cuadros y, cuando hay un evento,
    escribe un clip con lo que pasó antes y ``post_seconds`` después."""

    def __init__(self, store: EventStore, fps: float, pre_seconds: float, post_seconds: float):
        self.store = store
        self.fps = fps
        self.post = post_seconds
        self.buffer: deque[np.ndarray] = deque(maxlen=max(1, round(pre_seconds * fps)))
        self.pending: list[_PendingClip] = []

    def push(self, frame: np.ndarray, t: float) -> None:
        self.buffer.append(frame)
        still = []
        for p in self.pending:
            p.frames.append(frame)
            if t >= p.until_t:
                self._write(p)
            else:
                still.append(p)
        self.pending = still

    def start(self, ev: Event) -> None:
        name = f"{ev.id:06d}_{ev.camera_id}_{ev.rule}.mp4"
        self.pending.append(_PendingClip(ev.id, self.store.dir / "clips" / name, ev.t + self.post, list(self.buffer)))

    def flush(self) -> None:
        for p in self.pending:
            self._write(p)
        self.pending = []

    def _write(self, p: _PendingClip) -> None:
        if not p.frames:
            return
        h, w = p.frames[0].shape[:2]
        writer = cv2.VideoWriter(str(p.path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
        for f in p.frames:
            writer.write(f)
        writer.release()
        self.store.set_media(p.event_id, clip=str(p.path))
        log.info("Clip guardado: %s", p.path)


def save_snapshot(store: EventStore, frame: np.ndarray, ev: Event) -> str:
    path = store.dir / "snapshots" / f"{ev.id:06d}_{ev.camera_id}_{ev.rule}.jpg"
    cv2.imwrite(str(path), draw_event(frame, ev))
    store.set_media(ev.id, snapshot=str(path))
    return str(path)
