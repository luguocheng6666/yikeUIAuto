@echo off
REM 删除开发过程中产生的临时验证脚本（一次性，用完即删）
cd /d "%~dp0..\web"
del /f /q _verify_assert.py chk_assert.py chk_run.py chk_fixes.py chk_fixes2.py chk_fixes3.py 2>nul
echo done
