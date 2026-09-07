# Bug BUG-5004 日志分析报告

## 根因结论
API网关SSL证书过期导致HTTPS请求握手失败

## 问题触发时间
2026-08-12 11:05:00

## 关键日志依据
- 2026-08-12 11:04:50 [WARN] gateway - TLS 握手失败次数上升，最近 1 分钟 47 次
- 2026-08-12 11:05:02 [ERROR] gateway - SSL 证书校验失败：certificate has expired，域名 api.example.com 证书已于 2026-08-12 00:00 过期
- 2026-08-12 11:05:04 [ERROR] gateway - HTTPS 请求批量握手失败，javax.net.ssl.SSLHandshakeException，客户端报 ERR_CERT_DATE_INVALID
- 2026-08-12 11:05:08 [ERROR] web-app - 全站 API 调用失败率 98%，根因为网关证书过期导致 TLS 握手失败
- 2026-08-12 11:05:30 [WARN] pay-callback - 第三方支付回调全部失败，进入重试队列

## 分析步骤
1. 检查API网关错误日志，发现 SSL 证书校验失败 certificate has expired
2. 查看证书有效期，确认 api.example.com 证书已于 2026-08-12 00:00 过期
3. 确认 HTTPS 请求批量握手失败，javax.net.ssl.SSLHandshakeException，全站 API 调用失败率 98%
4. 更新 SSL 证书并重启网关，TLS 握手恢复正常，请求恢复