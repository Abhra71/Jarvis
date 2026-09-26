@echo off
rem Jarvis with logs in this window (Ctrl+C to stop)
cd /d "%~dp0"
.venv\Scripts\python.exe -m jarvis --console %*
pause
