@echo off
REM Raccourci de lancement Windows: demarre le serveur TGI sur http://localhost:8080
REM Double-cliquez sur ce fichier, ou lancez-le depuis PowerShell.
cd /d "%~dp0"
uv pip install --find-links vendor\ --no-index --no-deps -r vendor\requirements.txt -e .
uv run tgi
pause
