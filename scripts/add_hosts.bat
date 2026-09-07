@echo off
:: 添加 Diana AI 平台内网域名映射（需要管理员权限运行）
echo. >> C:\Windows\System32\drivers\etc\hosts
echo # Diana AI 平台内网映射 >> C:\Windows\System32\drivers\etc\hosts
echo 10.203.193.5    aidm-issue.apps-qa.saic-gm.com >> C:\Windows\System32\drivers\etc\hosts
echo 10.203.193.5    aigw01.apps-qa.saic-gm.com >> C:\Windows\System32\drivers\etc\hosts
echo.
echo hosts 文件已更新，内容如下：
echo ============================================
type C:\Windows\System32\drivers\etc\hosts
echo ============================================
echo.
echo 完成！连上网线后即可使用 Diana API。
pause
