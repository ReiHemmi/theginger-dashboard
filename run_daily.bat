@echo off
REM THE GINGER dashboard daily update (Task Scheduler)
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ==== %date% %time% ==== >> "data\run_daily.log"
".venv\Scripts\python.exe" run_daily.py >> "data\run_daily.log" 2>&1
REM Push updated DB to GitHub so Streamlit Cloud shows latest data
git add data\dashboard.db >> "data\run_daily.log" 2>&1
git commit -m "data update %date% %time%" >> "data\run_daily.log" 2>&1
git push >> "data\run_daily.log" 2>&1
endlocal
