@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The dashboard virtual environment was not found.
    echo Run install_autogluon.bat first.
    pause
    exit /b 1
)

set "WORKBOOK=%~1"
if "%WORKBOOK%"=="" (
    if exist "%CD%\DataV3.xlsx" (
        set "WORKBOOK=%CD%\DataV3.xlsx"
    ) else if exist "%CD%\DataV2.xlsx" (
        set "WORKBOOK=%CD%\DataV2.xlsx"
    ) else (
        echo Pass the workbook path as the first argument.
        echo Example: train_autogluon.bat "D:\path\to\Data.xlsx"
        pause
        exit /b 1
    )
)

echo Training AutoGluon model from:
echo %WORKBOOK%
call ".venv\Scripts\python.exe" "%CD%\train_autogluon.py" --workbook "%WORKBOOK%"
if errorlevel 1 (
    echo AutoGluon training failed.
    pause
    exit /b 1
)

echo AutoGluon training completed.
pause
exit /b 0
