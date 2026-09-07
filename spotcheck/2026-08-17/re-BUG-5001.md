# Bug BUG-5001 日志分析报告

## 根因结论
慢查询长时间占用连接未释放，导致数据库连接池耗尽并引发服务批量超时。

## 问题触发时间
2026-08-10 09:15:01（首次报出连接池耗尽及SQL异常）

## 关键日志依据
- 2026-08-10 09:15:01 [ERROR] order-service - 获取数据库连接超时（等待 5000ms），连接池已耗尽，active=50 idle=0
- 2026-08-10 09:15:03 [ERROR] order-service - java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 5000ms
- 2026-08-10 09:15:06 [ERROR] order-service - 下单接口 /api/order/create 批量超时，失败率 87%，根因指向数据库连接池耗尽
- 2026-08-10 09:25:33 [INFO] order-service - 慢查询扫描：SELECT * FROM t_order_detail WHERE status=0 执行耗时 28.4s，占用连接未释放

## 分析步骤
1. （第一步：发现的问题现象）09:14:38起order-service日志开始出现数据库连接等待时间飙升的WARN告警，至09:15:01连接池完全耗尽，下单接口批量请求超时，失败率高达87%，且故障开始向user-service扩散。
2. （第二步：深入排查的过程）结合日志时间线追踪，发现连接池活跃连接数已达上限50且空闲数为0，伴随HikariPool底层异常抛出；监控系统于09:16:40及时推送P1级告警，确认非瞬时网络抖动而是资源型阻塞。
3. （第三步：定位到的具体根因）通过回溯慢查询扫描日志，精准定位到SQL语句`SELECT * FROM t_order_detail WHERE status=0`执行耗时长达28.4秒且事务未正常提交/回滚，导致数据库连接被长期独占直至池资源枯竭。
4. （第四步：修复措施或建议）立即终止该慢查询并回收连接恢复服务；后续需为该表status字段添加索引、优化SQL逻辑或改为分批处理；调整HikariCP连接超时与最大生命周期参数，并接入慢SQL自动拦截与熔断机制。