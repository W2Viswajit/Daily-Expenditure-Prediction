@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project environment missing. Follow README.md setup instructions.
  exit /b 1
)
".venv\Scripts\python.exe" app.py %*
