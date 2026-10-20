@echo off
REM Run all regression tests: backend pytest + frontend node assertions.
REM Exit codes: 0 = all passed, 1 = failed, 2 = partially skipped (node missing).
REM Usage: tests\run-tests.bat
cd /d "%~dp0.."

REM Probe the interpreter instead of trusting venv\Scripts\python.exe to exist:
REM a copied or half-deleted venv still has the exe but cannot import pytest.
set "PY="
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import pytest" >nul 2>&1
    if not errorlevel 1 set "PY=venv\Scripts\python.exe"
)
if defined PY goto runpy

py -3 -c "import pytest" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto runpy

python -c "import pytest" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto runpy

goto nopy

:runpy
echo [1/2] backend (pytest) using %PY%
%PY% -m pytest tests -q
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

:nopy
echo.
echo pytest is not available in any interpreter.
echo Run setup.bat first to create venv and install requirements-dev.txt.
exit /b 1

:skip_front
echo.
echo PARTIAL: node not found in PATH - frontend check was SKIPPED.
echo Install Node 18+ and re-run, or run "node tests\front-check.js" manually.
exit /b 2

:fail
echo.
echo TESTS FAILED - see output above
exit /b 1
