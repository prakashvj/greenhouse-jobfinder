@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:5050
.venv\Scripts\python -m jobfinder.web
