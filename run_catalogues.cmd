@echo off
setlocal
chcp 65001 >nul
title Souschef - Maxi + Super C
cd /d "%~dp0"
echo Démarrage simultané de Maxi et Super C...
echo La fenêtre Edge de Maxi doit rester ouverte jusqu'à la fin.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\run_weekly_catalogues.py" --apply %*
) else (
  python "scripts\run_weekly_catalogues.py" --apply %*
)
if errorlevel 1 (
  echo.
  echo L'import hebdomadaire a echoue. Consultez le message ci-dessus.
  pause
  exit /b 1
)
echo.
echo Import hebdomadaire termine.
pause
