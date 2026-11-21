@echo off
setlocal
chcp 65001 >nul
title Morrow - Terminal Vocabulary System
cd /d "%~dp0" || exit /b 1

echo Starting Morrow...
if exist ".venv\Scripts\python.exe" goto venv
py -3 --version >nul 2>&1
if not errorlevel 1 goto launcher
python --version >nul 2>&1
if not errorlevel 1 goto python

echo Python 3 was not found. Install Python 3.10 or later and try again.
set "MORROW_EXIT=1"
goto done

:venv
".venv\Scripts\python.exe" morrow.py
goto save_exit

:launcher
py -3 morrow.py
goto save_exit

:python
python morrow.py

:save_exit
set "MORROW_EXIT=%ERRORLEVEL%"

:done
pause
exit /b %MORROW_EXIT%
