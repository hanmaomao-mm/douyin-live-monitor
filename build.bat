@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ------------------------------------------------------------
REM  打包脚本：生成 dist\DouyinLiveMonitor\DouyinLiveMonitor.exe
REM  需要一个装好依赖的 Python 环境（见 requirements.txt）
REM ------------------------------------------------------------

if "%VIRTUAL_ENV%"=="" (
    if exist ".build-venv\Scripts\python.exe" (
        set "PY=.build-venv\Scripts\python.exe"
    ) else (
        set "PY=python"
    )
) else (
    set "PY=python"
)

echo [1/2] 使用解释器: %PY%
%PY% -m PyInstaller DouyinLiveMonitor.spec --noconfirm --clean
if errorlevel 1 goto :err

echo [2/2] 完成
echo 输出目录: %~dp0dist\DouyinLiveMonitor\
echo 可执行文件: %~dp0dist\DouyinLiveMonitor\DouyinLiveMonitor.exe
exit /b 0

:err
echo 打包失败，请查看上方日志。
exit /b 1
