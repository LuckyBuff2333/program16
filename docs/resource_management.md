# 资源管理与监控系统

## 概述

本系统实现了三个核心功能：
1. 资源自动清理和监控机制
2. 系统健康度和性能监控
3. 优化缓存策略

## 1. 资源自动清理和监控机制

### 功能特点

- **系统资源监控**：实时监控CPU、内存、磁盘使用情况
- **自动清理**：定期清理过期文件句柄和无用对象
- **阈值报警**：当资源使用超过设定阈值时发出警告
- **垃圾回收**：自动触发Python垃圾回收机制

### 实现模块

位于 `src/core/resource_monitor.py`：

- `ResourceTracker`：资源跟踪器，跟踪文件和对象资源
- `HealthMonitor`：健康度监控器，收集系统指标
- `PerformanceMonitor`：性能监控器，记录响应时间和吞吐量

### API 接口

- `GET /api/system/health` - 获取系统健康状态
- `GET /api/system/cache-stats` - 获取缓存统计信息
- `POST /api/system/cleanup` - 手动清理资源

## 2. 系统健康度和性能监控

### 监控指标

#### 资源指标
- CPU 使用率 (%)
- 内存使用率 (%)
- 内存使用量 (MB)
- 磁盘使用率 (%)

#### 性能指标
- 平均响应时间 (ms)
- P95/P99 响应时间 (ms)
- 吞吐量 (请求/秒)
- 错误率 (%)

### 阈值配置

- CPU 阈值：80%
- 内存阈值：85%
- 磁盘阈值：90%

## 3. 优化缓存策略

### 功能特点

- **LRU缓存**：实现最近最少使用缓存淘汰算法
- **TTL支持**：支持缓存项过期时间
- **多级缓存**：支持不同用途的缓存分区
- **文件缓存**：支持持久化缓存到文件系统
- **统计监控**：提供缓存命中率等统计信息

### 实现模块

位于 `src/core/cache_manager.py`：

- `LRUCache`：基于OrderedDict的LRU缓存实现
- `CacheManager`：高级缓存管理器，支持多租户缓存
- `FileBasedCache`：基于文件的持久化缓存

### 使用示例

```python
from src.core import cache_manager

# 获取指定名称的缓存
my_cache = cache_manager.get_cache('my_cache', max_size=500, ttl=1800)

# 存储数据
my_cache.put('key', 'value')

# 获取数据
value = my_cache.get('key')

# 使用缓存装饰器
@cache_manager.cache_function_result('my_func_cache', ttl=3600)
def expensive_function(param):
    # 耗时操作
    return result
```

## 4. 在现有系统中的集成

### Pipeline 模块优化

- **JIRA Issue 缓存**：缓存JIRA issue数据，TTL 30分钟
- **AI分析结果缓存**：缓存AI分析结果，避免重复计算

### Web 服务优化

- **上传文件缓存**：使用LRU缓存管理上传文件数据
- **性能监控**：在关键API端点记录性能指标
- **定时清理**：每10分钟执行一次资源清理

## 5. 使用方法

### 查看系统健康状态

```bash
curl http://localhost:8000/api/system/health
```

### 查看缓存统计

```bash
curl http://localhost:8000/api/system/cache-stats
```

### 手动清理资源

```bash
curl -X POST http://localhost:8000/api/system/cleanup
```

## 6. 配置参数

### 资源监控配置

- 监控间隔：5秒
- 历史数据保留：100条记录
- 资源阈值：可配置

### 缓存配置

- 默认最大大小：1000项
- 默认TTL：1小时
- 不同用途缓存可独立配置

## 7. 注意事项

1. 缓存大小应根据可用内存合理设置
2. TTL值应根据数据更新频率设置
3. 定期检查监控指标，及时发现性能问题
4. 在生产环境中适当调整阈值参数