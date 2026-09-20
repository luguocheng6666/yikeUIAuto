@echo off
title yikeUIAuto Web 平台
cd /d "%~dp0"

rem cmd 默认 GBK，让 Python 输出也用 GBK，避免中文乱码
set PYTHONIOENCODING=gbk:replace

echo ============================================
echo   yikeUIAuto Web 用例管理平台
echo   访问地址: http://127.0.0.1:8000
echo   账号: admin   密码: 123456
echo ============================================
echo.

echo [1/3] 检查 MySQL 服务...
net start MySQL80 >nul 2>&1
if errorlevel 1 (
    echo       MySQL 已在运行，或需要手动启动服务 MySQL80
) else (
    echo       MySQL80 已启动
)

echo [2/3] 检查 Python 环境...
if not exist ".python3\python.exe" (
    echo [错误] 未找到 .python3\python.exe
    goto :end
)

echo [3/3] 启动 Web 服务（关闭此窗口即停止）...
echo.
start "" http://127.0.0.1:8000/login/
cd /d "%~dp0web"
"..\.python3\python.exe" manage.py runserver 127.0.0.1:8000 --noreload

:end
echo.
pause
