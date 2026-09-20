@echo off
REM yikeUIAuto 自动化测试一键运行（Windows）
REM
REM 用独立的 SQLite 测试库，不碰正式 MySQL 库，也不需要 MySQL 处于启动状态。
REM 常用法：
REM   run_tests.bat               跑全部
REM   run_tests.bat cases        只跑用例导入导出
REM   run_tests.bat runner       只跑执行/清理相关
REM   run_tests.bat cases.tests.ImportBasicTests           跑到某个类
REM   run_tests.bat %1 -v 2      加 -v 2 可以看到每条用例的名字

setlocal
set PY="%~dp0..\.python3\python.exe"
set WEB=%~dp0..web

if not exist %PY% set PY=python

pushd "%WEB%"
%PY% manage.py test %* --settings=yikeui.settings_test
popd

echo.
echo 退出码：%ERRORLEVEL%
pause
