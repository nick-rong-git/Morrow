@echo off
chcp 65001 >nul
title Morrow - Terminal Vocabulary System
cd /d "%~dp0"
echo.
echo ========================================================
echo   ✦ MORROW ✦ 极简终端背单词系统 (Build for Tomorrow)
echo ========================================================
echo.
"C:\Users\Administrator\AppData\Local\Python\bin\python.exe" morrow.py
pause
