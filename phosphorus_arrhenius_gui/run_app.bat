@echo off
set "APP_DIR=%~dp0..\\"
if exist "%APP_DIR%.venv\Scripts\python.exe" (
  "%APP_DIR%.venv\Scripts\python.exe" "%APP_DIR%phosphorus_sublimation_gui.py"
) else (
  python "%APP_DIR%phosphorus_sublimation_gui.py"
)
pause
