@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ==========================================
echo   Bug 文档沉淀工具 - 智能打包脚本
echo ==========================================
echo.

cd /d "%~dp0.."

:: 检查是否有旧 exe 正在运行，有则自动结束
tasklist /FI "IMAGENAME eq bug-doc-tool.exe" 2>NUL | find /I "bug-doc-tool.exe" >NUL
if %ERRORLEVEL%==0 (
    echo [INFO] 检测到 bug-doc-tool.exe 正在运行，正在结束进程...
    taskkill /F /IM bug-doc-tool.exe >NUL 2>&1
    timeout /t 2 /nobreak >NUL
)

:: 清理 build 目录（避免文件锁定问题）
if exist build (
    echo [INFO] 清理旧的 build 目录...
    rmdir /s /q build 2>NUL
    if exist build (
        echo [WARN] build 目录清理失败，可能有文件被占用
        echo [INFO] 尝试使用备用输出名...
        set EXTRA_ARGS=--distpath dist2
    )
)

:: 执行打包
echo [INFO] 开始打包...
pyinstaller bug-doc-tool.spec --noconfirm %EXTRA_ARGS%
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] 打包失败，请检查错误信息
    pause
    exit /b 1
)

echo.
echo [DONE] 打包完成！
echo [PATH] 输出目录: %CD%\dist\
echo [FILE] bug-doc-tool.exe

:: 显示文件大小
for %%A in (dist\bug-doc-tool.exe) do (
    set size=%%~zA
    set /a sizeMB=!size!/1048576
    echo [SIZE] 约 !sizeMB! MB
)
echo.
pause
