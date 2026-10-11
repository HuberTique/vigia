"""API HTTP mínima para consultar y revisar eventos (base del panel web)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from vigia.events import EventStore


class Review(BaseModel):
    review: str | None  # valid | false_alarm | null


def create_app(data_dir: str) -> FastAPI:
    store = EventStore(data_dir)
    app = FastAPI(title="Vigia", description="Eventos de riesgo detectados en cámaras")

    @app.get("/events")
    def list_events(limit: int = 100, camera_id: str | None = None, rule: str | None = None):
        return store.list(limit=limit, camera_id=camera_id, rule=rule)

    @app.get("/events/{event_id}")
    def get_event(event_id: int):
        ev = store.get(event_id)
        if not ev:
            raise HTTPException(404, "Evento no encontrado")
        return ev

    @app.post("/events/{event_id}/review")
    def review_event(event_id: int, body: Review):
        try:
            ok = store.set_review(event_id, body.review)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if not ok:
            raise HTTPException(404, "Evento no encontrado")
        return store.get(event_id)

    def _media(event_id: int, field: str) -> FileResponse:
        ev = store.get(event_id)
        if not ev or not ev.get(field) or not Path(ev[field]).exists():
            raise HTTPException(404, "Archivo no disponible")
        return FileResponse(ev[field])

    @app.get("/events/{event_id}/snapshot")
    def snapshot(event_id: int):
        return _media(event_id, "snapshot_path")

    @app.get("/events/{event_id}/clip")
    def clip(event_id: int):
        return _media(event_id, "clip_path")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _INDEX_HTML

    return app


# Bandeja de alertas mínima; el panel completo (Next.js) la reemplaza más adelante.
_INDEX_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vigia - Alertas</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#111;color:#eee}
h1{font-size:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:#1d1d1d;border-radius:8px;overflow:hidden}.card img{width:100%;display:block}
.body{padding:10px;font-size:14px}.high{color:#ff6b6b}.medium{color:#ffd166}
button{margin-right:6px;padding:4px 8px;border-radius:4px;border:0;cursor:pointer}
.rev{font-size:12px;color:#aaa}
</style></head><body>
<h1>Alertas recientes</h1><div id="g" class="grid"></div>
<script>
async function load(){
  const evs = await (await fetch('events?limit=60')).json();
  document.getElementById('g').innerHTML = evs.map(e => `
    <div class="card">
      ${e.snapshot_path ? `<img src="events/${e.id}/snapshot" loading="lazy">` : ''}
      <div class="body">
        <div class="${e.severity}"><b>${e.rule}</b> · ${e.camera_id}${e.zone ? ' · ' + e.zone : ''}</div>
        <div>${e.message}</div><div class="rev">${e.occurred_at} · revisión: ${e.review ?? 'pendiente'}</div>
        ${e.clip_path ? `<a href="events/${e.id}/clip" style="color:#8ecae6">Ver clip</a><br>` : ''}
        <button onclick="rev(${e.id},'valid')">Válida</button><button onclick="rev(${e.id},'false_alarm')">Falsa alarma</button>
      </div></div>`).join('') || '<p>Sin alertas todavía.</p>';
}
async function rev(id, r){
  await fetch(`events/${id}/review`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({review:r})});
  load();
}
load(); setInterval(load, 5000);
</script></body></html>"""
