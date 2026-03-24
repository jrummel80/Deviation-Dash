@echo off
setlocal

cd /d "%~dp0"

set "OPEN_BROWSER=1"
if /I "%~1"=="--no-browser" set "OPEN_BROWSER=0"

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
    echo Install Python, then run this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    call "%BOOTSTRAP_CMD%" %BOOTSTRAP_ARGS% -m venv .venv
    if errorlevel 1 goto :fail
)

echo Installing or updating dashboard requirements...
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8501 .*LISTENING"') do (
    echo Stopping existing process on port 8501: %%P
    taskkill /PID %%P /F >nul 2>nul
)

echo Starting Deviation Dash server...
start "Deviation Dash Server" /D "%CD%" "%CD%\.venv\Scripts\python.exe" -m streamlit run "%CD%\streamlit_app.py" --server.port 8501 --server.headless true
call :wait_for_server
if errorlevel 1 goto :server_not_ready

if "%OPEN_BROWSER%"=="1" (
    call :open_browser
)

echo Deviation Dash is available at http://localhost:8501
exit /b 0

:wait_for_server
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$deadline=(Get-Date).AddSeconds(90);" ^
    "do {" ^
    "  try {" ^
    "    $response = Invoke-WebRequest -UseBasicParsing 'http://localhost:8501' -TimeoutSec 3;" ^
    "    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { exit 0 }" ^
    "  } catch {}" ^
    "  Start-Sleep -Seconds 1" ^
    "} while((Get-Date) -lt $deadline);" ^
    "exit 1"
exit /b %errorlevel%

:open_browser
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if defined CHROME_EXE (
    start "" "%CHROME_EXE%" "http://localhost:8501"
    goto :eof
)

start "" "http://localhost:8501"
goto :eof

:server_not_ready
echo The dashboard server did not respond on http://localhost:8501 within 90 seconds.
echo Check the "Deviation Dash Server" window for startup errors, then run this file again.
pause
exit /b 1

:fail
echo Dashboard startup failed.
pause
exit /b 1
