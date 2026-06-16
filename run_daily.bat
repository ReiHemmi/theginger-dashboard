@echo off
REM THE GINGER ダッシュボード 毎日更新（タスクスケジューラから呼ばれる）
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ==== %date% %time% ==== >> "data\run_daily.log"
".venv\Scripts\python.exe" run_daily.py >> "data\run_daily.log" 2>&1
endlocal
