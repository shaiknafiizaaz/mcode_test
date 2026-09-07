@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo    R+L CARRIERS BOL / TENET-EBS JOB ASSISTANT - LOCAL MODE
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3 was not found on PATH.
    echo.
    echo Install Python 3 from https://www.python.org/downloads/
    echo and make sure "Add python.exe to PATH" is checked.
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking Python dependencies...
python -c "import fastapi, uvicorn, jinja2, PIL, pypdf, requests" >nul 2>nul
if errorlevel 1 (
    echo       Installing dependencies from requirements.txt...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Dependency installation failed. Check the message above.
        pause
        exit /b 1
    )
)

echo [2/3] Checking Ollama (optional - only needed for image upload)...
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=1)" >nul 2>nul
if errorlevel 1 (
    echo       Ollama not detected. Image upload will be unavailable.
    echo       Paste Text and Manual Entry work fully offline.
    echo       To enable images:  ollama pull qwen2.5vl   then restart.
) else (
    echo       Ollama detected.
)

echo [3/3] Starting the assistant on http://127.0.0.1:8000 ...
echo       (Keep this window open while you use the app. Close it to stop.)
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8000"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
echo.
echo Server stopped.
pause