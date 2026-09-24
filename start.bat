@echo off
setlocal
cd /d "%~dp0"
title GlassMatch

rem ===== Create .venv if missing (goto style: no %errorlevel% inside blocks) =====
if exist ".venv\Scripts\python.exe" goto ensure

echo [GlassMatch] First run: creating virtual environment (.venv)...
where uv >nul 2>nul
if errorlevel 1 goto try_py
uv venv .venv --python 3.11
if exist ".venv\Scripts\python.exe" goto ensure
uv venv .venv
if exist ".venv\Scripts\python.exe" goto ensure
goto try_py

:try_py
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3.11 -m venv .venv
if exist ".venv\Scripts\python.exe" goto ensure
py -3 -m venv .venv
if exist ".venv\Scripts\python.exe" goto ensure
goto try_python

:try_python
python -m venv .venv
if exist ".venv\Scripts\python.exe" goto ensure

echo [GlassMatch] ERROR: could not create a virtual environment.
echo Install Python 3.11+ from https://www.python.org/downloads/
echo ^(check "Add python.exe to PATH", then run this file again^)
call :wait
exit /b 1

rem ===== Install dependencies only if missing =====
:ensure
".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if not errorlevel 1 goto run

echo [GlassMatch] Installing dependencies (first run only)...
where uv >nul 2>nul
if errorlevel 1 goto pip_install
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto pip_install
goto run

:pip_install
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto fail_deps
goto run

:fail_deps
echo [GlassMatch] ERROR: dependency install failed. Check your network and re-run.
call :wait
exit /b 1

rem ===== Run =====
:run
echo [GlassMatch] Starting http://localhost:8501  ^(close this window to stop^)
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
".venv\Scripts\python.exe" -m streamlit run app.py %* <nul
if errorlevel 1 (
    echo.
    echo [GlassMatch] Streamlit exited with an error.
    call :wait
)
endlocal
exit /b 0

:wait
timeout /t 20 >nul 2>nul || ping -n 21 127.0.0.1 >nul
exit /b
