@echo off
setlocal
cd /d "%~dp0"

rem Pick an interpreter that can actually import deps. A copied/broken venv
rem can still have python.exe present but fail at runtime; old version had no fallback.
set "PY="
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import fastapi, uvicorn, PIL" >nul 2>&1
    if not errorlevel 1 set "PY=venv\Scripts\python.exe"
)
if defined PY goto run

py -3 -c "import fastapi, uvicorn, PIL" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run

python -c "import fastapi, uvicorn, PIL" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run

goto nodeps

:run
echo [FoodMap] 使用解释器: %PY%
%PY% -m app.main
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto failed
endlocal
exit /b 0

:nodeps
echo.
echo [FoodMap] 没找到可用的 Python 环境（缺少 fastapi / uvicorn / Pillow）。
echo   1. 安装 Python 3.10 或更高版本，安装时勾选 Add python.exe to PATH
echo   2. 在本目录运行 setup.bat，自动创建 venv 并安装依赖
echo   3. 再运行 start.bat
echo.
pause
endlocal
exit /b 1

:failed
echo.
echo [FoodMap] 启动失败（退出码 %RC%）。
echo   若上方提示 ModuleNotFoundError，运行 setup.bat 重新安装依赖。
echo.
pause
endlocal
exit /b %RC%
