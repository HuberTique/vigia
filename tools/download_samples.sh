#!/usr/bin/env bash
# Descarga videos de prueba públicos a ./videos
# Fuente: https://github.com/intel-iot-devkit/sample-videos (licencia CC BY 4.0)
set -euo pipefail
mkdir -p videos
base=https://media.githubusercontent.com/media/intel-iot-devkit/sample-videos/master
for f in people-detection.mp4 one-by-one-person-detection.mp4; do
  echo "Descargando $f"
  curl -fsSL -o "videos/$f" "$base/$f"
done
echo "Listo: $(ls videos)"
