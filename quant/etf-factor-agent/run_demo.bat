@echo off
cd /d "%~dp0"
python agent.py demo --out results/demo
if errorlevel 1 (
  echo Demo failed. Install Python 3.10 or later and inspect the message above.
  pause
  exit /b 1
)
start "" "results\demo\report.html"
pause
