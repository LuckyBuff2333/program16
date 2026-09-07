# Bug BUG-5001 日志分析报告

## 根因结论
数据库连接池耗尽导致服务超时

## 问题触发时间
2026-08-10 09:15:00

## 关键日志依据
- 2026-08-10 09:14:38 [WARN] order-service - 数据库连接等待时间 850ms，接近告警阈值
- 2026-08-10 09:14:52 [WARN] order-service - 数据库连接等待时间 2300ms，连接池活跃连接数 48/50
- 2026-08-10 09:15:01 [ERROR] order-service - 获取数据库连接超时（等待 5000ms），连接池已耗尽，active=50 idle=0
- 2026-08-10 09:15:03 [ERROR] order-service - java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms
- 2026-08-10 09:15:06 [ERROR] order-service - 下单接口 /api/order/create 批量超时，失败率 87%，根因指向数据库连接池耗尽
- 2026-08-10 09:15:18 [WARN] user-service - 数据库连接等待时间 3100ms，疑似连接池资源不足扩散

## 分析步骤
1. 查看服务错误日志，发现大量数据库连接超时错误，连接池活跃连接数达到上限
2. 分析连接池监控指标，确认 HikariPool 活跃连接 50/50，idle=0，连接池已耗尽
3. 定位到慢查询 SELECT * FROM t_order_detail 执行耗时 28.4s，长期占用连接未释放
4. 修复慢SQL并扩大连接池配置，服务恢复正常