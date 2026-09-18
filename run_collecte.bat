@echo off
REM Collecte planifiee JobApply — lance toutes les recherches de recherches.json
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0backend"
python daily_collect.py --show
