@echo off
rem Jarvis in the background with a tray icon, no console window
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe -m jarvis
