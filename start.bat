@echo off
cd /d "%~dp0"
IF EXIST venv\Scripts\python.exe (
    venv\Scripts\python.exe -m app.main
) ELSE (
    python -m app.main
)
