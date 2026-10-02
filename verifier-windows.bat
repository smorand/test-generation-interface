@echo off
REM Verifie, sur Windows, ce que DRIFT-004 de SPEC-0001a n'a pas pu mesurer ailleurs.
REM Double cliquer sur ce fichier. Rien d'autre a faire.

cd /d "%~dp0"

echo.
echo   Verification des noms de peripheriques reserves Windows
echo   =======================================================
echo.

echo [1/3] Mise a jour des dependances...
call uv sync
if errorlevel 1 goto erreur

echo.
echo [2/3] Execution de la mesure...
call uv run python scripts\verify_windows.py
if errorlevel 2 goto pas_windows

echo.
echo [3/3] Enregistrement du resultat dans la branche...
call git add specs\SPEC-0001a_2026-10-01_14-01-27-cwe22-path-containment\DRIFT-004-windows-evidence.txt
call git commit -m "Evidence DRIFT-004: mesure des noms de peripheriques sur Windows"
if errorlevel 1 echo    (rien a committer, le resultat etait deja enregistre)

echo.
echo   ----------------------------------------------------------
echo   Termine. Il reste a envoyer le resultat :
echo.
echo       git push
echo.
echo   Puis revenir dire que c'est pousse.
echo   ----------------------------------------------------------
echo.
pause
exit /b 0

:pas_windows
echo.
echo   Ce script ne mesure quelque chose que sur Windows.
echo.
pause
exit /b 2

:erreur
echo.
echo   Echec. Si "uv n'est pas reconnu", fermer cette fenetre, en ouvrir
echo   une nouvelle, et reessayer : voir WINDOWS.md etape 1.
echo.
pause
exit /b 1
