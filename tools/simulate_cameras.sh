#!/usr/bin/env bash
# Publica videos locales como cámaras RTSP, igual que lo haría una cámara IP o un NVR.
#
#   ./tools/simulate_cameras.sh videos/merodeo.mp4 videos/robo.mp4
#
# Crea rtsp://localhost:8554/cam1, cam2, ... (uno por video, en bucle).
# Requiere Docker (para MediaMTX) y ffmpeg.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Uso: $0 video1.mp4 [video2.mp4 ...]" >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q '^vigia-mediamtx$'; then
  echo "Iniciando MediaMTX..."
  docker run -d --rm --name vigia-mediamtx -p 8554:8554 bluenviron/mediamtx:latest >/dev/null
  sleep 2
fi

pids=()
trap 'kill "${pids[@]}" 2>/dev/null; docker stop vigia-mediamtx >/dev/null 2>&1 || true' EXIT

i=1
for video in "$@"; do
  url="rtsp://localhost:8554/cam$i"
  echo "cam$i <- $video  ($url)"
  ffmpeg -hide_banner -loglevel error -re -stream_loop -1 -i "$video" \
    -c:v libx264 -preset veryfast -tune zerolatency -an -f rtsp "$url" &
  pids+=($!)
  i=$((i + 1))
done

echo "Cámaras simuladas activas. Ctrl+C para detener."
wait
