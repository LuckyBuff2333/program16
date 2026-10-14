"""通用资源锁工具：按 key 懒创建线程安全锁，防止并发操作同一资源

典型场景：
- 按 document_id 加锁，避免并发写入同一飞书文档
- 按 bugid 加锁，避免并发分析同一 bug
"""
import threading
from typing import Dict


class KeyedLockPool:
    """按 key 管理互斥锁的锁池，支持懒创建和过期清理"""

    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str) -> threading.Lock:
        """获取指定 key 的锁（不存在则自动创建），线程安全"""
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def remove(self, key: str) -> None:
        """移除指定 key 的锁（用于清理不再使用的资源）"""
        with self._guard:
            self._locks.pop(key, None)

    def clear(self) -> None:
        """清空所有锁"""
        with self._guard:
            self._locks.clear()

    @property
    def size(self) -> int:
        """当前管理的锁数量"""
        with self._guard:
            return len(self._locks)
