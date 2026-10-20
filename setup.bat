@echo off
setlocal
cd /d "%~dp0"

rem Create (or reuse) venv and install runtime + dev dependencies.
rem Goal: reproduce a working env on another machine without memorising pip commands.

set "BOOT="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "BOOT=py -3"
if defined BOOT goto havepy

python -c "import sys" >nul 2>&1
if not errorlevel 1 set "BOOT=python"
if defined BOOT goto havepy

goto nopy

:havepy
echo [FoodMap] 使用 %BOOT% 准备 venv...
if not exist "venv\Scripts\python.exe" (
    %BOOT% -m venv venv
    if errorlevel 1 goto fail
) else (
    echo [FoodMap] 复用已存在的 venv
)

echo [FoodMap] 安装依赖（requirements.txt + requirements-dev.txt）...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
"venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 goto fail

"venv\Scripts\python.exe" -c "import fastapi, uvicorn, PIL, pytest; print('[FoodMap] 依赖就绪')"
if errorlevel 1 goto fail

echo.
echo [FoodMap] 环境准备完成：
echo   启动应用：start.bat
echo   运行测试：venv\Scripts\python.exe -m pytest tests -q
echo   前端回归：node tests\front-check.js
echo.
pause
endlocal
exit /b 0

:nopy
echo.
echo [FoodMap] 没有找到 Python（py 或 python 均不可用）。
echo   请先安装 Python 3.10 或更高版本，安装时勾选 Add python.exe to PATH，
echo   然后重新运行 setup.bat。
echo.
pause
endlocal
exit /b 1

:fail
echo.
echo [FoodMap] 依赖安装失败，请检查网络或代理后重试。
echo   也可以手工执行：
echo     venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
echo.
pause
endlocal
exit /b 1
