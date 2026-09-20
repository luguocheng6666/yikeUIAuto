@echo off
REM 产物清理 —— 保留最近 100 份报告 / 100 天内的 BackUP
REM 可直接双击运行，也可以交给 Windows 计划任务每天跑一次：
REM   schtasks /create /tn "yikeUIAuto 产物清理" /tr "\"%~f0\"" /sc daily /st 03:00
cd /d "%~dp0..\web"
"..\.python3\python.exe" manage.py cleanup_artifacts
