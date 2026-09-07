@echo off
chcp 65001 >nul
echo 正在清理 hosts 文件中的 Diana/AIDM 映射...
echo.

:: 备份原文件
copy "C:\Windows\System32\drivers\etc\hosts" "C:\Windows\System32\drivers\etc\hosts.bak.%date:~0,4%%date:~5,2%%date:~8,2%" >nul 2>&1

:: 读取并过滤掉 Diana 相关行
powershell -Command "Get-Content 'C:\Windows\System32\drivers\etc\hosts' | Where-Object { $_ -notmatch 'Diana AI' -and $_ -notmatch '10\.22\.127\.11.*saic-gm\.com' } | Set-Content 'C:\Windows\System32\drivers\etc\hosts' -Encoding UTF8"

echo.
echo 清理完成！当前 hosts 内容：
echo ============================================
type C:\Windows\System32\drivers\etc\hosts
echo ============================================
echo.
pause
