"""Línea de comandos: ``vigia run``, ``vigia snapshot`` y ``vigia api``."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime

import cv2

from vigia.config import load_config


def _parse_start(text: str | None) -> datetime | None:
    if not text:
        return None
    if len(text) <= 5:  # "23:00"
        h, m = map(int, text.split(":"))
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    return datetime.fromisoformat(text)


def cmd_run(args) -> int:
    from vigia.events import EventStore
    from vigia.perception.detector import build_detector
    from vigia.pipeline import CameraPipeline

    cfg = load_config(args.config)
    cams = [c for c in cfg.cameras if not args.camera or c.id in args.camera]
    if not cams:
        print(f"No hay cámaras con id {args.camera}", file=sys.stderr)
        return 2
    if args.save_video and len(cams) > 1:
        print("--save-video sólo funciona con una cámara (usa --camera)", file=sys.stderr)
        return 2

    store = EventStore(cfg.data_dir)
    notifiers = []
    if cfg.telegram.enabled:
        from vigia.notify.telegram import TelegramNotifier

        notifiers.append(TelegramNotifier(cfg.telegram))

    detector = build_detector(cfg.model)
    lock = threading.Lock()
    pipelines = [
        CameraPipeline(
            cfg,
            cam,
            detector,
            store,
            notifiers,
            detector_lock=lock,
            start_time=_parse_start(args.start_time),
            loop=args.loop,
            save_video=args.save_video,
        )
        for cam in cams
    ]
    threads = [threading.Thread(target=p.run, kwargs={"max_seconds": args.max_seconds}, name=p.cam.id, daemon=True) for p in pipelines]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        return 0
    total = sum(len(p.events) for p in pipelines)
    print(f"Listo. {total} evento(s) guardados en {store.db_path}")
    failed = [p.cam.id for p in pipelines if p.error]
    if failed:
        print(f"Cámaras con error: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def cmd_snapshot(args) -> int:
    """Guarda un cuadro de la cámara con una cuadrícula normalizada (0..1)
    para leer fácilmente las coordenadas de las zonas."""
    from vigia.ingest import VideoSource

    cfg = load_config(args.config)
    cam = next((c for c in cfg.cameras if c.id == args.camera), None)
    if cam is None:
        print(f"No existe la cámara {args.camera}", file=sys.stderr)
        return 2
    frame = next(VideoSource(cam.source, cfg.analysis_fps).frames())
    img = frame.image.copy()
    h, w = img.shape[:2]
    for i in range(1, 10):
        x, y = round(w * i / 10), round(h * i / 10)
        cv2.line(img, (x, 0), (x, h), (255, 255, 255), 1)
        cv2.line(img, (0, y), (w, y), (255, 255, 255), 1)
        cv2.putText(img, f"{i / 10:.1f}", (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        cv2.putText(img, f"{i / 10:.1f}", (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    cv2.imwrite(args.output, img)
    print(f"Cuadro guardado en {args.output} ({w}x{h})")
    return 0


def cmd_api(args) -> int:
    import uvicorn

    from vigia.api import create_app

    cfg = load_config(args.config)
    notifiers = []
    if cfg.telegram.enabled:
        from vigia.notify.telegram import TelegramNotifier

        notifiers.append(TelegramNotifier(cfg.telegram))
    app = create_app(cfg.data_dir, config_path=args.config, notifiers=notifiers, preload_model=True)
    url = f"http://localhost:{args.port}"
    print(f"\n  Vigia está listo en {url}\n  Deja esta ventana abierta; Ctrl+C para apagar.\n")
    if getattr(args, "open_browser", False):
        import webbrowser

        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vigia", description="Detección de riesgos en cámaras de seguridad")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Analizar las cámaras configuradas")
    r.add_argument("-c", "--config", default="configs/demo.yaml")
    r.add_argument("--camera", action="append", help="Analizar sólo esta cámara (se puede repetir)")
    r.add_argument("--start-time", help="Hora simulada de inicio para videos, ej. 23:00 o 2026-10-10T23:00")
    r.add_argument("--loop", action="store_true", help="Repetir el video en bucle")
    r.add_argument("--max-seconds", type=float, help="Detener después de N segundos de video")
    r.add_argument("--save-video", help="Guardar el video anotado (una sola cámara)")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("snapshot", help="Guardar un cuadro con cuadrícula para dibujar zonas")
    s.add_argument("-c", "--config", default="configs/demo.yaml")
    s.add_argument("--camera", required=True)
    s.add_argument("-o", "--output", default="snapshot.jpg")
    s.set_defaults(func=cmd_snapshot)

    for name, help_text, open_default in (
        ("ui", "Abrir la interfaz gráfica en el navegador", True),
        ("api", "Servir la interfaz y la API sin abrir el navegador", False),
    ):
        a = sub.add_parser(name, help=help_text)
        a.add_argument("-c", "--config", default="configs/demo.yaml")
        a.add_argument("--host", default="127.0.0.1", help="0.0.0.0 para abrirla desde otros equipos de la red")
        a.add_argument("--port", type=int, default=8000)
        a.set_defaults(func=cmd_api, open_browser=open_default)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
