@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo GUI環境が未セットアップです。SEへ連絡してください。
  echo 準備手順: リポジトリ直下で uv sync --project media-shrink-tool --extra gui --extra dev
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m media_shrink gui
if errorlevel 1 (
  echo 起動または実行に失敗しました。上の説明を確認してSEへ連絡してください。
  pause
  exit /b 1
)
endlocal
