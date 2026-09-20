@echo off
title yikeUIAuto 自动化测试
cd /d "%~dp0"

echo ============================================
echo   yikeUIAuto 关键字驱动自动化测试
echo   项目目录: %CD%
echo ============================================
echo.

if not exist ".python3\python.exe" (
    echo [错误] 未找到 .python3\python.exe
    echo 请先安装项目内置 Python，或检查目录是否完整。
    goto :end
)

echo [检查] 测试用例文件是否被 Excel / WPS 占用...
if exist "Data\~$testdata.xlsx" (
    echo.
    echo [错误] Data\testdata.xlsx 正在被 Excel 或 WPS 打开。
    echo 请先关闭该表格，否则执行结果无法写回 Excel。
    goto :end
)

echo [运行] 开始执行测试，请稍候...
echo.
rem cmd 默认代码页是 GBK，让 Python 输出也用 GBK，避免中文日志乱码
set PYTHONIOENCODING=gbk:replace
".python3\python.exe" testsuites\TestRunner.py

echo.
echo ============================================
echo   执行完成
echo   测试报告: reports\result.html
echo   结果已回写: Data\testdata.xlsx
echo ============================================
echo.

set OPEN=N
set /p OPEN=是否打开测试报告? [Y/N] 直接回车跳过:
if /i "%OPEN%"=="Y" start "" "reports\result.html"

:end
echo.
pause
