#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
资源管理与监控系统测试脚本
"""

import time
from src.core import resource_monitor, cache_manager


def test_cache_functionality():
    """测试缓存功能"""
    print("=== 测试缓存功能 ===")
    
    # 获取一个缓存实例
    test_cache = cache_manager.get_cache('test_cache', max_size=5, ttl=60)
    
    # 存储一些数据
    for i in range(5):
        test_cache.put(f'key_{i}', f'value_{i}')
        print(f"存储: key_{i} -> value_{i}")
    
    # 读取数据
    for i in range(5):
        value = test_cache.get(f'key_{i}')
        print(f"读取: key_{i} -> {value}")
    
    # 超出大小测试 - 添加第六个项目，应该触发LRU淘汰
    test_cache.put('key_5', 'value_5')
    print(f"存储: key_5 -> value_5 (此时key_0应该被淘汰)")
    
    # 尝试获取key_0，应该为None
    value = test_cache.get('key_0')
    print(f"读取: key_0 -> {value} (应该为None，因为已被淘汰)")
    
    # 检查缓存统计
    stats = cache_manager.get_cache_stats()
    print(f"缓存统计: {stats}")
    

def test_resource_monitoring():
    """测试资源监控功能"""
    print("\n=== 测试资源监控功能 ===")
    
    # 记录一些性能指标
    for i in range(3):
        resource_monitor.performance_monitor.record_request(100 + i * 10, True)  # 模拟响应时间
        resource_monitor.performance_monitor.increment_throughput()
        print(f"记录性能指标 {i+1}")
        time.sleep(0.1)  # 短暂延迟
    
    # 获取系统健康状态
    health = resource_monitor.get_system_health()
    print(f"系统健康状态: {health}")


def test_manual_cleanup():
    """测试手动清理功能"""
    print("\n=== 测试手动清理功能 ===")
    
    # 执行手动清理
    resource_monitor.cleanup_resources()
    print("手动清理完成")


if __name__ == "__main__":
    print("开始测试资源管理与监控系统...\n")
    
    test_cache_functionality()
    test_resource_monitoring()
    test_manual_cleanup()
    
    print("\n所有测试完成！")