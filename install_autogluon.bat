@echo off
setlocal

cd /d "%~dp0"

set "GPU_MODE=0"
if /I "%~1"=="--gpu" set "GPU_MODE=1"

set "BOOTSTRAP_CMD="
set "BOOTSTRAP_ARGS="

where py >nul 2>nul
if %errorlevel%==0 (
    set "BOOTSTRAP_CMD=py"
    set "BOOTSTRAP_ARGS=-3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "BOOTSTRAP_CMD=python"
    )
)

if not defined BOOTSTRAP_CMD (
    echo Python 3 was not found on this machine.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    call "%BOOTSTRAP_CMD%" %BOOTSTRAP_ARGS% -m venv .venv
    if errorlevel 1 goto :fail
)

echo Installing base dashboard requirements...
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Installing AutoGluon requirements...
call ".venv\Scripts\python.exe" -m pip install -r requirements-autogluon.txt
if errorlevel 1 goto :fail

if "%GPU_MODE%"=="1" (
    echo Installing CUDA-enabled PyTorch for NVIDIA GPU training...
    call ".venv\Scripts\python.exe" -m pip install --upgrade --force-reinstall --no-deps torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu126
    if errorlevel 1 goto :fail
    call ".venv\Scripts\python.exe" -m pip install "numpy<2.2"
    if errorlevel 1 goto :fail
)

echo AutoGluon installation completed.
exit /b 0

:fail
echo AutoGluon installation failed.
pause
exit /b 1
