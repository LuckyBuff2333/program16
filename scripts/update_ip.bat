@echo off
:: 快速更新 AI 日志分析接口 IP
:: 用法: update_ip.bat 10.22.127.11
::
:: 自动替换 config.yaml 和 check_network.py 中的旧 IP

if "%~1"=="" (
    echo 用法: update_ip.bat ^<新IP^>
    echo 示例: update_ip.bat 10.22.127.11
    echo.
    echo 当前配置的 IP:
    findstr "10\." d:\program16\config\config.yaml | findstr "url"
    pause
    exit /b
)

set NEW_IP=%~1
echo 更新 AI 日志分析接口 IP 为: %NEW_IP%
echo.

:: 用 PowerShell 替换 config.yaml 中的 IP
powershell -Command "(Get-Content 'd:\program16\config\config.yaml') -replace 'http://[\d.]+:8001', 'http://%NEW_IP%:8001' | Set-Content 'd:\program16\config\config.yaml'"
echo [config.yaml] 已更新

:: 用 PowerShell 替换 check_network.py 中的 IP
powershell -Command "(Get-Content 'd:\program16\scripts\check_network.py') -replace 'http://[\d.]+:8001', 'http://%NEW_IP%:8001' | Set-Content 'd:\program16\scripts\check_network.py'"
echo [check_network.py] 已更新

echo.
echo 验证:
findstr "8001" d:\program16\config\config.yaml
echo.
echo 完成！无需重启后端（load_config 每次读取最新配置）
pause
