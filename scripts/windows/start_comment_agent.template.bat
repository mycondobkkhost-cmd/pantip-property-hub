@echo off
chcp 65001 >nul
title ระบบคอมเมนต์เฟส PTP
cd /d "%~dp0..\.."

REM ไฟล์นี้เป็นตัวอย่าง — แนะนำให้ดาวน์โหลดจาก Hub แทน (ใส่ค่าให้อัตโนมัติแล้ว)
set "HUB_URL=__HUB_URL__"
set "COMMENT_AGENT_TOKEN=__AGENT_TOKEN__"

echo.
echo ระบบคอมเมนต์เฟสอัตโนมัติ
echo เปิดทิ้งไว้ — อย่าปิดหน้าต่างนี้
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo เครื่องนี้ยังไม่มี Python — ให้หัวหน้าทีมติดตั้งก่อน
  pause
  exit /b 1
)

python scripts\comment_agent.py --hub "%HUB_URL%" --token "%COMMENT_AGENT_TOKEN%"
echo.
echo ระบบหยุดแล้ว
pause
