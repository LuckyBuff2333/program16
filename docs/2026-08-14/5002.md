# Bug BUG-5002 日志分析报告

## 根因结论
订单服务内存泄漏引发OOM进程重启

## 问题触发时间
2026-08-11 14:32:00

## 关键日志依据
- 2026-08-11 14:10:22 [WARN] order-service - JVM 老年代使用率 82%，Full GC 频率上升
- 2026-08-11 14:20:33 [WARN] order-service - JVM 老年代使用率 91%，Full GC 耗时 1.8s，存在内存泄漏迹象
- 2026-08-11 14:30:41 [ERROR] order-service - Full GC 耗时 6.2s，老年代回收率不足 5%，堆内存持续增长无法回收
- 2026-08-11 14:31:55 [ERROR] order-service - 大对象缓存 OrderExportCache 持有 240 万条记录未释放，确认为内存泄漏点
- 2026-08-11 14:32:02 [ERROR] order-service - java.lang.OutOfMemoryError: Java heap space，进程触发 OOM 自动重启

## 分析步骤
1. 排查订单服务内存使用情况，发现 JVM 老年代使用率从 82% 持续增长至 91%
2. 分析GC日志，确认 Full GC 耗时 6.2s 且回收率不足 5%，堆内存持续增长不回收
3. 定位到 OrderExportCache 持有 240 万条记录未释放，确认为内存泄漏点
4. 修复未关闭的数据库会话并清理缓存，服务重启后内存恢复正常