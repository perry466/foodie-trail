@echo off
REM Run all regression tests: backend pytest + frontend node assertions.
REM Exit codes: 0 = all passed, 1 = failed, 2 = partially skipped (node missing).
REM Usage: tests\run-tests.bat
cd /d "%~dp0.."

set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/2] backend (pytest)
"%PY%" -m pytest tests -q
if errorlevel 1 goto fail

echo.
echo [2/2] frontend (node)
where node >nul 2>nul
if errorlevel 1 goto skip_front

node "tests\front-check.js"
if errorlevel 1 goto fail

echo.
echo ALL TESTS PASSED
exit /b 0

:skip_front
echo.
echo PARTIAL: node not found in PATH - frontend check was SKIPPED.
echo Install Node 18+ and re-run, or run "node tests\front-check.js" manually.
exit /b 2

:fail
echo.
echo TESTS FAILED - see output above
exit /b 1
