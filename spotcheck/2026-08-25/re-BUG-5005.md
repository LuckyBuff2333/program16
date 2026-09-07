# Bug BUG-5005 日志分析报告

## 根因结论
慢SQL全表扫描锁表导致业务线程阻塞堆积

## 问题触发时间
2026-08-13 16:20:00

## 关键日志依据
- 2026-08-13 16:18:42 [WARN] report-service - SQL 执行耗时 8.3s，语句 SELECT * FROM t_trade_record WHERE create_time > '2026-01-01'，未命中索引
- 2026-08-13 16:19:36 [WARN] db-monitor - 表 t_trade_record 锁等待会话数 35，持续增长
- 2026-08-13 16:20:04 [ERROR] report-service - 慢SQL全表扫描 1200 万行并持有表锁，执行耗时 56s，触发锁表
- 2026-08-13 16:20:08 [ERROR] order-service - 业务线程阻塞堆积：等待 t_trade_record 行锁的线程达 210 个，线程池使用率 100%
- 2026-08-13 16:20:15 [ERROR] gateway - 下游接口 /api/trade/query 超时率 92%，根因为慢SQL锁表导致业务线程阻塞
- 2026-08-13 16:20:38 [WARN] pay-service - 交易查询超时，自动降级为缓存读

## 分析步骤
1. 查看数据库慢查询日志，发现全表扫描操作：SELECT * FROM t_trade_record 执行耗时 56s
2. 分析业务线程状态，确认等待 t_trade_record 行锁的线程达 210 个，线程池使用率 100%
3. 定位到订单查询SQL缺少索引导致全表扫描锁表，业务线程阻塞堆积
4. 添加索引 idx_create_time 并优化SQL，kill 慢SQL会话后服务恢复正常