@echo off
REM Open real Google Chrome using the profile selected in Hub
set ROOT=%~dp0..\..
cd /d "%ROOT%"

set HUB_URL=%HUB_URL%
if "%HUB_URL%"=="" set HUB_URL=https://hub.realxtateth.com
if "%COMMENT_AGENT_ID%"=="" set COMMENT_AGENT_ID=owner
if "%FB_CDP_PORT%"=="" set FB_CDP_PORT=9222

echo ========================================
echo   Open real Chrome for Agent
echo ========================================
echo.

python scripts\launch_chrome_for_agent.py --hub "%HUB_URL%" --token "%COMMENT_AGENT_TOKEN%" --agent "%COMMENT_AGENT_ID%" --port "%FB_CDP_PORT%"
if errorlevel 1 (
  echo.
  echo If Python failed, install Python 3 and try again.
)
echo.
pause
