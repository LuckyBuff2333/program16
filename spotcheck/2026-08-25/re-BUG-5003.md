# Bug BUG-5003 日志分析报告

## 根因结论
Redis集群节点宕机引发缓存雪崩压垮数据库

## 问题触发时间
2026-08-12 03:47:00

## 关键日志依据
- 2026-08-12 03:46:28 [WARN] cache-service - 节点 redis-node-2 响应延迟 450ms，疑似网络抖动
- 2026-08-12 03:46:55 [ERROR] cache-service - 节点 redis-node-2 心跳丢失，集群标记节点 FAIL
- 2026-08-12 03:47:03 [ERROR] goods-service - Redis 连接异常 JedisConnectionException: Could not get a resource from the pool，大批量请求开始穿透缓存
- 2026-08-12 03:47:10 [ERROR] goods-service - 缓存雪崩发生：热点 key 集中失效叠加节点宕机，数据库 QPS 从 800 激增至 9200
- 2026-08-12 03:47:22 [ERROR] db-monitor - 数据库 CPU 使用率 99%，活跃会话 480，被缓存穿透流量压垮
- 2026-08-12 03:47:40 [WARN] order-service - 依赖商品接口超时，熔断器开启

## 分析步骤
1. 检查Redis集群状态，发现 redis-node-2 节点网络抖动导致心跳丢失，集群标记节点 FAIL
2. 分析缓存命中率，确认节点宕机引发缓存雪崩，热点 key 集中失效
3. 确认大量缓存请求穿透到数据库，数据库 QPS 从 800 激增至 9200，CPU 使用率 99%
4. 重启 Redis 节点并补充缓存降级策略，数据库压力恢复正常