@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else if exist "%USERPROFILE%\PycharmProjects\Anka\.venv\Scripts\python.exe" (
    "%USERPROFILE%\PycharmProjects\Anka\.venv\Scripts\python.exe" main.py
) else (
    py -3 main.py
)
if errorlevel 1 (
    echo.
    echo Launch failed. See README.md for setup instructions.
    pause
)
endlocal
