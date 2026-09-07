@echo off
rem Allure 报告启动器：内置 JAVA_HOME 与工具路径，任何终端直接运行即可，不依赖系统环境变量
setlocal
rem 切换到脚本所在目录（项目根目录），保证相对路径 allure-results 在任何启动方式下都正确
cd /d "%~dp0"

rem 检查测试结果数据是否存在，避免生成空报告
if not exist "allure-results\*-result.json" (
    echo [错误] allure-results 下未找到测试结果数据！
    echo 请先运行: python -m pytest tests --alluredir=allure-results
    pause
    exit /b 1
)

set "JAVA_HOME=d:\program16\tools\jdk-17.0.20+8-jre"
set "ALLURE_BIN=d:\program16\tools\allure-2.45.0\bin\allure.bat"

if "%~1"=="" goto serve
rem 用法1：allure-serve.bat           启动临时服务查看报告（自动打开浏览器，Ctrl+C 退出）
rem 用法2：allure-serve.bat generate   生成单文件静态报告到 allure-report\ 并打开（可直接双击查看）
if /i "%~1"=="generate" (
    rem --single-file 将数据内联进 HTML，避免直接打开时浏览器报 Failed to fetch
    call "%ALLURE_BIN%" generate allure-results -o allure-report --clean --single-file
    if exist "allure-report\index.html" start "" "allure-report\index.html"
    goto end
)
if /i "%~1"=="serve" goto serve
echo 未知参数: %~1（仅支持 serve / generate）
pause
exit /b 1

:serve
call "%ALLURE_BIN%" serve allure-results

:end
endlocal
