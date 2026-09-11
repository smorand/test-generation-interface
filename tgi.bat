@echo off
REM Raccourci de lancement Windows: demarre le serveur TGI sur http://localhost:8080
REM Double-cliquez sur ce fichier, ou lancez-le depuis PowerShell.
cd /d "%~dp0"
set HTTPS_PROXY=https://145.226.163.45:8080
set HTTP_PROXY=http://145.226.163.45:8080
set UV_SYSTEM_CERTS=1
uv sync
uv run tgi
pause
