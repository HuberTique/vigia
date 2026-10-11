# Vigia

Software que se conecta a cámaras CCTV (cámaras IP, DVR y NVR por RTSP) y detecta comportamientos de riesgo en tiempo real.

**Versión 0.1 (MVP):**

| Escenario | Estado | Cómo funciona |
|---|---|---|
| Merodeo | ✅ | Una persona permanece más de N segundos en una zona vigilada. |
| Intrusión por puerta, ventana o zona restringida | ✅ | Una persona entra a la zona; las puertas pueden vigilar sólo en un horario (ej. 22:00-06:00) y las ventanas alertan siempre. |
| Objeto abandonado | ✅ | Una mochila, bolso o maleta queda quieta y sin nadie cerca. |
| Escaleras humanas / escalamiento | 🔜 | Pose (esqueletos). |
| Peleas | 🔜 | Pose + clasificador de acciones. |
| Armas y cuchillos | 🔜 | Detector afinado + verificación con un modelo de visión-lenguaje. |

Cada alerta guarda una **foto anotada**, un **clip** con los segundos de antes y después, un registro en **SQLite**, y puede enviarse por **Telegram**. Una bandeja web permite marcar cada alerta como válida o falsa alarma (eso será el dato para reentrenar).

## Arquitectura

```
Cámara / NVR (RTSP) o video
   │
   ▼
ingest.py ──► perception/detector.py ──► perception/tracker.py ──► rules/*.py ──► events.py ──► Telegram
 (5 fps)       YOLO26 o RF-DETR           ByteTrack                 una regla       SQLite + foto     api.py (bandeja web)
                                                                     por escenario   + clip
```

- **Modelos intercambiables:** el detector se elige en la configuración (`model.backend: ultralytics | rfdetr`). YOLO26 es AGPL-3.0; RF-DETR (nano a large) es Apache 2.0 y conviene para un producto comercial cerrado.
- **Reglas independientes:** cada escenario es una clase en `vigia/rules/` con la misma interfaz. Se activan y ajustan por cámara y por zona.
- **Zonas normalizadas (0 a 1):** sirven aunque cambie la resolución de la cámara.

## Instalación

Requiere Python 3.10 o superior.

```bash
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -e ".[yolo,dev]"      # o ".[rfdetr,dev]" para usar RF-DETR
pytest                             # pruebas de las reglas, sin modelos ni video
```

Los pesos del modelo (`yolo26n.pt`) se descargan solos la primera vez.

## Probarlo sin cámaras

**Opción 1: el ejemplo listo con un video público.**

```bash
./tools/download_samples.sh                     # videos de prueba de Intel (CC BY 4.0) en ./videos
vigia run -c configs/ejemplo_video.yaml --start-time 23:00 --save-video demo_out.mp4
```

Detecta a las personas, las sigue con un ID y genera una alerta de intrusión cuando alguien entra por la puerta de la izquierda "a las 23:00". Para usar tu propio video, cambia `source` por su ruta.

`--start-time` simula la hora de grabación para probar reglas con horario. `demo_out.mp4` queda con las cajas, IDs y zonas dibujadas.

**Opción 2: simular cámaras RTSP reales** (requiere Docker y ffmpeg):

```bash
./tools/simulate_cameras.sh videos/merodeo.mp4 videos/robo.mp4   # crea rtsp://localhost:8554/cam1 y cam2
vigia run -c configs/demo.yaml
```

**Opción 3: tu celular como cámara IP** con una app como "IP Webcam" (Android) y su URL RTSP o HTTP en `source`.

Videos de prueba públicos: UCF-Crime (robos, intrusiones, peleas), ABODA y PETS 2006 (objetos abandonados), VIRAT (exteriores). Revisa sus licencias. Los clips que grabes tú actuando cada escenario son los más útiles para ajustar los umbrales.

## Configurar zonas

```bash
vigia snapshot -c configs/demo.yaml --camera cam1 -o snapshot.jpg
```

Guarda un cuadro con una cuadrícula de 0.1 en 0.1. Lee las esquinas de cada zona y escríbelas en `configs/demo.yaml`:

```yaml
zones:
  - name: puerta_principal
    kind: door                 # loitering | restricted | door | window
    polygon: [[0.40, 0.30], [0.60, 0.30], [0.60, 0.95], [0.40, 0.95]]
    schedules: ["22:00-06:00"] # opcional; sin horario vigila siempre
    params: {confirm_seconds: 2}  # opcional; umbrales propios de la zona
```

## Bandeja de alertas y API

```bash
vigia api -c configs/demo.yaml     # http://localhost:8000
```

- `GET /events`: últimas alertas (filtros `camera_id`, `rule`, `limit`).
- `GET /events/{id}/snapshot` y `/clip`: foto y video del evento.
- `POST /events/{id}/review` con `{"review": "valid" | "false_alarm"}`.

## Alertas por Telegram

1. Crea un bot con @BotFather y copia el token.
2. Escríbele al bot y obtén tu `chat_id` (por ejemplo con @userinfobot).
3. `export TELEGRAM_BOT_TOKEN=...` y `export TELEGRAM_CHAT_ID=...`
4. En la configuración pon `notify.telegram.enabled: true`.

## Conectar cámaras reales

Casi todas las cámaras IP y los DVR/NVR exponen RTSP. Usa el **substream** (baja resolución) para el análisis; así no se afecta la grabación. Ejemplos de URL:

- Hikvision: `rtsp://usuario:clave@IP:554/Streaming/Channels/102`
- Dahua: `rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=1`
- TP-Link Tapo: `rtsp://usuario:clave@IP:554/stream2`

## Hoja de ruta

1. Pose (YOLO26-pose o RTMO) para escaleras humanas y escalamiento.
2. Peleas: heurística con pose y luego clasificador de esqueletos (PoseC3D).
3. Armas: datos auto-etiquetados con SAM 3, detector RF-DETR afinado y confirmación en varios cuadros.
4. Verificación de alertas con un modelo de visión-lenguaje antes de notificar.
5. Panel web completo, MQTT, PostgreSQL y despliegue con Docker Compose en un mini PC o Jetson.

## Estructura

```
configs/            configuración de cámaras, zonas y reglas
tools/              simulador de cámaras RTSP y descarga de videos de prueba
vigia/
  ingest.py         lectura de archivos y streams con reconexión
  perception/       detector (YOLO26 / RF-DETR) y tracker (ByteTrack)
  rules/            una regla por escenario
  events.py         SQLite, fotos y clips
  notify/           Telegram
  pipeline.py       bucle de análisis por cámara
  api.py            API y bandeja web
  cli.py            comandos run, snapshot y api
tests/              pruebas de reglas, configuración y API
```
