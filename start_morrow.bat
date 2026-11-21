@echo off
chcp 65001 >nul
title Morrow - Terminal Vocabulary System
cd /d "%~dp0"
echo Starting Morrow...
"C:\Users\Administrator\AppData\Local\Python\bin\python.exe" morrow.py
pause
