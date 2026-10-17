@echo off
chcp 65001 >nul
cd /d %~dp0
python -m pip install -q fastapi uvicorn httpx
start "" http://127.0.0.1:8765
python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
