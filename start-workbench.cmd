@echo off
setlocal
cd /d "%~dp0"
set "MORI_NODE=node"
where node >nul 2>nul
if errorlevel 1 set "MORI_NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "node_modules\vite\package.json" (
  echo Dependencies are missing. Install Node.js 22+, then run: npm install
  pause
  exit /b 1
)
echo MORI Workbench: http://127.0.0.1:5173
echo Keep this window open while using the workbench.
"%MORI_NODE%" server\index.mjs
pause
