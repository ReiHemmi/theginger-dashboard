@echo off
chcp 65001 >nul
REM THE GINGER ダッシュボードを起動してブラウザで開く（ダブルクリックで実行）
cd /d "%~dp0"
echo THE GINGER ダッシュボードを起動します...
echo ブラウザが自動で開きます。終了するときはこの黒い画面を閉じてください。
".venv\Scripts\streamlit.exe" run app/dashboard.py --server.port 8501
