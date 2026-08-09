#!/usr/bin/env bash
# Raccourci de lancement macOS/Linux: demarre le serveur TGI sur http://localhost:8080
set -euo pipefail
cd "$(dirname "$0")"
exec uv run tgi
