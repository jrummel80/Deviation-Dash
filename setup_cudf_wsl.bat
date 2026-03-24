@echo off
setlocal

cd /d "%~dp0"

echo Checking WSL distributions...
wsl -l -v
if errorlevel 1 (
    echo.
    echo WSL is not ready yet. Reboot Windows first, then launch Ubuntu once to finish first-time setup.
    pause
    exit /b 1
)

echo Copying RAPIDS setup script into Ubuntu...
wsl -d Ubuntu -- bash -lc "mkdir -p ~/deviation-dash"
if errorlevel 1 goto :firstlaunch

type "%CD%\scripts\setup_rapids_wsl.sh" | wsl -d Ubuntu -- bash -lc "cat > ~/deviation-dash/setup_rapids_wsl.sh && chmod +x ~/deviation-dash/setup_rapids_wsl.sh"
if errorlevel 1 goto :firstlaunch

echo Running RAPIDS/cuDF setup inside Ubuntu...
wsl -d Ubuntu -- bash -lc "~/deviation-dash/setup_rapids_wsl.sh"
if errorlevel 1 goto :fail

echo.
echo cuDF setup completed inside WSL Ubuntu.
pause
exit /b 0

:firstlaunch
echo.
echo Ubuntu needs its first-launch setup completed.
echo Open Ubuntu once from the Start menu, create your Linux username/password, close it, then run this file again.
pause
exit /b 1

:fail
echo.
echo cuDF setup did not finish successfully.
pause
exit /b 1
