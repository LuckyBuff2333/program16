"""缓存管理器：实现LRU缓存和智能缓存策略"""
import threading
import time
from collections import OrderedDict
from typing import Any, Optional, Callable, Dict
from datetime import datetime, timedelta
import hashlib
import pickle
import os
from pathlib import Path

from src.config import PROJECT_ROOT, setup_logger

logger = setup_logger("cache_manager")


class LRUCache:
    """LRU缓存实现"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl  # 秒
        self.cache = OrderedDict()
        self.access_times = {}  # key -> access_time
        self.creation_times = {}  # key -> creation_time
        self.lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self.lock:
            # 检查是否过期
            if key in self.creation_times:
                creation_time = self.creation_times[key]
                if time.time() - creation_time > self.ttl:
                    # 过期，删除缓存
                    self._remove_key(key)
                    return None
            
            if key in self.cache:
                # 更新访问时间
                self.access_times[key] = time.time()
                # 移动到末尾（LRU）
                value = self.cache.pop(key)
                self.cache[key] = value
                return value
            return None
    
    def put(self, key: str, value: Any):
        """放入缓存值"""
        with self.lock:
            # 如果键已存在，更新值
            if key in self.cache:
                self.cache[key] = value
                self.access_times[key] = time.time()
                self.creation_times[key] = time.time()
                return
            
            # 如果缓存已满，删除最少使用的项
            if len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.cache))
                self._remove_key(oldest_key)
            
            # 添加新的键值对
            self.cache[key] = value
            now = time.time()
            self.access_times[key] = now
            self.creation_times[key] = now
    
    def _remove_key(self, key: str):
        """内部方法：删除键"""
        if key in self.cache:
            del self.cache[key]
        if key in self.access_times:
            del self.access_times[key]
        if key in self.creation_times:
            del self.creation_times[key]
    
    def delete(self, key: str):
        """删除指定键"""
        with self.lock:
            self._remove_key(key)
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.access_times.clear()
            self.creation_times.clear()
    
    def size(self) -> int:
        """获取缓存大小"""
        with self.lock:
            return len(self.cache)
    
    def keys(self) -> list:
        """获取所有键"""
        with self.lock:
            # 清除过期的键
            expired_keys = []
            current_time = time.time()
            for key, creation_time in self.creation_times.items():
                if current_time - creation_time > self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                self._remove_key(key)
            
            return list(self.cache.keys())


class CacheManager:
    """高级缓存管理器"""
    
    def __init__(self):
        self.caches = {}
        self.default_ttl = 3600  # 默认1小时
        self.default_max_size = 1000
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_puts': 0
        }
        self.stats_lock = threading.Lock()
        self.lock = threading.RLock()
    
    def get_cache(self, cache_name: str, max_size: int = None, ttl: int = None) -> LRUCache:
        """获取或创建缓存实例"""
        with self.lock:
            if cache_name not in self.caches:
                max_size = max_size or self.default_max_size
                ttl = ttl or self.default_ttl
                self.caches[cache_name] = LRUCache(max_size=max_size, ttl=ttl)
            return self.caches[cache_name]
    
    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """从指定缓存获取值"""
        cache = self.get_cache(cache_name)
        value = cache.get(key)
        with self.stats_lock:
            if value is not None:
                self.stats['hits'] += 1
            else:
                self.stats['misses'] += 1
        return value
    
    def put(self, cache_name: str, key: str, value: Any, ttl: int = None):
        """放入指定缓存"""
        cache = self.get_cache(cache_name, ttl=ttl)
        cache.put(key, value)
        with self.stats_lock:
            self.stats['total_puts'] += 1
    
    def delete(self, cache_name: str, key: str):
        """删除指定键"""
        cache = self.get_cache(cache_name)
        cache.delete(key)
    
    def clear_cache(self, cache_name: str):
        """清空指定缓存"""
        if cache_name in self.caches:
            cache = self.caches[cache_name]
            with self.stats_lock:
                self.stats['evictions'] += cache.size()
            cache.clear()
    
    def clear_all(self):
        """清空所有缓存"""
        for cache_name in list(self.caches.keys()):
            self.clear_cache(cache_name)
    
    def get_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        with self.stats_lock:
            stats = dict(self.stats)
            # 添加命中率
            total = stats['hits'] + stats['misses']
            stats['hit_rate'] = stats['hits'] / total if total > 0 else 0
            return stats
    
    def get_cache_sizes(self) -> Dict[str, int]:
        """获取各缓存大小"""
        sizes = {}
        for name, cache in self.caches.items():
            sizes[name] = cache.size()
        return sizes
    
    def cleanup_expired(self):
        """清理所有缓存中的过期项"""
        for cache in self.caches.values():
            # 通过访问所有键来触发过期清理
            keys = cache.keys()  # 这会自动清理过期项


class FileBasedCache:
    """基于文件的缓存，用于持久化缓存"""
    
    def __init__(self, cache_dir: str = ""):
        # 默认使用 PROJECT_ROOT/data/cache，遵循本地路径约定
        if not cache_dir:
            cache_dir = os.path.join(PROJECT_ROOT, "data", "cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.file_ttl = 86400  # 默认24小时
    
    def _get_cache_file_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        # 使用哈希避免非法字符
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"
    
    def get(self, key: str) -> Optional[Any]:
        """从文件获取缓存"""
        file_path = self._get_cache_file_path(key)
        if not file_path.exists():
            return None
        
        # 检查文件是否过期
        if time.time() - file_path.stat().st_mtime > self.file_ttl:
            file_path.unlink()
            return None
        
        try:
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            logger.error(f"读取缓存文件失败 {file_path}: {e}")
            # 删除损坏的缓存文件
            if file_path.exists():
                file_path.unlink()
            return None
    
    def put(self, key: str, value: Any):
        """写入文件缓存"""
        file_path = self._get_cache_file_path(key)
        try:
            with open(file_path, 'wb') as f:
                pickle.dump(value, f)
        except Exception as e:
            logger.error(f"写入缓存文件失败 {file_path}: {e}")
    
    def delete(self, key: str):
        """删除缓存文件"""
        file_path = self._get_cache_file_path(key)
        if file_path.exists():
            file_path.unlink()
    
    def cleanup_expired(self):
        """清理过期的缓存文件"""
        for cache_file in self.cache_dir.glob("*.cache"):
            if time.time() - cache_file.stat().st_mtime > self.file_ttl:
                try:
                    cache_file.unlink()
                    logger.info(f"已删除过期缓存文件: {cache_file}")
                except Exception as e:
                    logger.error(f"删除缓存文件失败 {cache_file}: {e}")


# 全局缓存管理器实例
cache_manager = CacheManager()
file_cache = FileBasedCache()


def get_cache(cache_name: str, max_size: int = None, ttl: int = None) -> LRUCache:
    """便捷函数：获取缓存实例"""
    return cache_manager.get_cache(cache_name, max_size, ttl)


def cache_function_result(cache_name: str, ttl: int = 3600, max_size: int = 100):
    """装饰器：缓存函数结果"""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{func.__name__}_{hash(str(args) + str(kwargs))}"
            
            # 尝试从缓存获取
            cached_result = cache_manager.get(cache_name, cache_key)
            if cached_result is not None:
                return cached_result
            
            # 执行函数并缓存结果
            result = func(*args, **kwargs)
            cache_manager.put(cache_name, cache_key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


def clear_cache(cache_name: str):
    """便捷函数：清空指定缓存"""
    cache_manager.clear_cache(cache_name)


def get_cache_stats():
    """获取缓存统计信息"""
    return {
        'stats': cache_manager.get_stats(),
        'sizes': cache_manager.get_cache_sizes(),
        'total_caches': len(cache_manager.caches)
    }


# 初始化时清理过期缓存
cache_manager.cleanup_expired()
file_cache.cleanup_expired()

logger.info("缓存管理系统已初始化")