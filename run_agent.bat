@echo off
cd /d "%~dp0"
title JobApply - Agent local
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" backend\local_agent.py
) else (
  python backend\local_agent.py
)
if errorlevel 1 pause
