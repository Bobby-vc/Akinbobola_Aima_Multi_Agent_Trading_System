@echo off
rem Runs the daily watchlist. Windows Task Scheduler calls this each weekday;
rem see "Daily Watchlist Runs" in the README. The one-line summary per ticker
rem is appended to logs\scheduler.log; full agent output goes to
rem logs\watchlist-<date>.log.

cd /d "%~dp0.."
if not exist logs mkdir logs

rem Task Scheduler may not have uv on its PATH, so fall back to uv's default install folder
set "UV=uv"
where uv >nul 2>nul || set "UV=%USERPROFILE%\.local\bin\uv.exe"

rem Avoids encoding errors when output is written to the log on Windows
set PYTHONIOENCODING=utf-8

echo ===== %DATE% %TIME% ===== >> logs\scheduler.log
"%UV%" run run_watchlist >> logs\scheduler.log 2>&1
