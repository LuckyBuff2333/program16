@echo off
:: 更新 hosts 中 Diana 域名映射为 10.22.127.11
powershell -Command "$h = Get-Content 'C:\Windows\System32\drivers\etc\hosts'; $h = $h -replace '10\.203\.193\.5', '10.22.127.11'; Set-Content 'C:\Windows\System32\drivers\etc\hosts' $h -Encoding ASCII"
echo.
echo 更新后 hosts 内容：
findstr /i "diana\|10\." C:\Windows\System32\drivers\etc\hosts
echo.
echo 完成！
pause
