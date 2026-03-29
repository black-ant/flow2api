@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found: .venv\Scripts\activate.bat
    echo Please create or restore the virtual environment first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo Starting flow2api...
python main.py

set EXIT_CODE=%ERRORLEVEL%
echo.
echo Process exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
