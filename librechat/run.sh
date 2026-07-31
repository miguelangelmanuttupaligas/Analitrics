#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

mkdir -p images uploads logs data-node meili_data_v1.35.1

docker compose up -d
