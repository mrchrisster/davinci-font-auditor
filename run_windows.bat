@echo off
cd /d "%~dp0"
echo =============================================
echo Starting DaVinci Font Mapper...
echo =============================================

rem Check for python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python could not be found.
    echo Please install Python and ensure "Add Python to PATH" is checked during installation.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing/updating dependencies...
python -m pip install -r requirements.txt

echo Starting backend server on http://127.0.0.1:5001...
start http://127.0.0.1:5001
python app.py

pause
