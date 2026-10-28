@echo off
rem Allure 报告启动器（自动探测 Java，不写死路径）
rem 用法：
rem   allure-serve.bat            启动临时服务查看报告（Ctrl+C 退出）
rem   allure-serve.bat generate   生成单文件静态报告到 allure-report\ 并打开
rem   allure-serve.bat check      只检查环境（Java / allure / 测试结果）
rem   allure-serve.bat --download 自动下载 Temurin JRE 17 到 tools\ 后再启动
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ALLURE_BIN=%ROOT%tools\allure-2.45.0\bin\allure.bat"
set "MODE=%~1"
set "JAVA_CMD="

rem 1) 优先用 JAVA_HOME
if defined JAVA_HOME if exist "%JAVA_HOME%\bin\java.exe" set "JAVA_CMD=%JAVA_HOME%\bin\java.exe"

rem 2) PATH 里的 java
if not defined JAVA_CMD for /f "delims=" %%J in ('where java 2^>nul') do set "JAVA_CMD=%%J"

rem 3) tools\jdk-*（跳过占位文件：小于 10KB 的 java.exe 视为无效）
if not defined JAVA_CMD for /d %%D in ("%ROOT%tools\jdk-*") do (
    for %%F in ("%%~fD\bin\java.exe") do (
        if %%~zF GTR 10000 if exist "%%~fD\bin\java.exe" (
            set "JAVA_HOME=%%~fD"
            set "JAVA_CMD=%%~fD\bin\java.exe"
        )
    )
)

if not defined JAVA_CMD goto :no_java
"%JAVA_CMD%" -version >nul 2>&1
if errorlevel 1 (
    echo [错误] 检测到 Java 但无法运行：%JAVA_CMD%
    echo         可能是占位文件或安装损坏。
    set "JAVA_CMD="
    goto :no_java
)

:after_java
echo [环境] Java: %JAVA_CMD%
"%JAVA_CMD%" -version
if not exist "%ALLURE_BIN%" (
    echo [错误] 找不到 allure：%ALLURE_BIN%
    goto :fail
)
set "HAS_RESULT=0"
if exist "allure-results\*-result.json" set "HAS_RESULT=1"

if /i "%MODE%"=="check" (
    echo [检查] allure-results 测试结果： 
    if "%HAS_RESULT%"=="1" (echo    OK) else (echo    缺失，请先运行: python -m pytest tests --alluredir=allure-results)
    goto :end
)

if "%HAS_RESULT%"=="0" (
    echo [错误] allure-results 下未找到测试结果数据！
    echo 请先运行: python -m pytest tests --alluredir=allure-results
    goto :fail
)

if "%MODE%"=="" goto :serve
if /i "%MODE%"=="serve" goto :serve
if /i "%MODE%"=="generate" (
    rem --single-file 把数据内联进 HTML，避免直接打开时浏览器报 Failed to fetch
    call "%ALLURE_BIN%" generate allure-results -o allure-report --clean --single-file
    if exist "allure-report\index.html" start "" "allure-report\index.html"
    goto :end
)
if /i "%MODE%"=="--download" goto :serve
echo 未知参数: %MODE%（支持 serve / generate / check / --download）
goto :fail

:serve
call "%ALLURE_BIN%" serve allure-results
goto :end

:no_java
echo [提示] 未检测到可用的 Java（Allure 需要 JRE 17+）。
echo.
echo   方式一（推荐）：安装系统 Java 17+ 后重试
echo   方式二：本脚本自动下载 Temurin JRE 17 到 tools\：
echo       allure-serve.bat --download
if /i "%MODE%"=="--download" goto :download
if /i "%MODE%"=="check" exit /b 1
pause
exit /b 1

:download
echo [下载] 正在获取 Temurin JRE 17（约 40MB）...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse' -OutFile 'tools\jre17.zip'; Expand-Archive -Path 'tools\jre17.zip' -DestinationPath 'tools' -Force; Remove-Item 'tools\jre17.zip'"
if errorlevel 1 (
    echo [错误] 下载或解压失败，请手动下载 JRE 17 解压到 tools\ 下。
    goto :fail
)
for /d %%D in ("%ROOT%tools\jdk-17*jre") do if exist "%%~fD\bin\java.exe" set "JAVA_CMD=%%~fD\bin\java.exe"
if not defined JAVA_CMD (
    echo [错误] 下载完成但未找到 java.exe，请检查 tools\ 目录。
    goto :fail
)
goto :after_java

:fail
pause
endlocal
exit /b 1

:end
endlocal
exit /b 0
