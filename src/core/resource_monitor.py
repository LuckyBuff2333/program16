"""资源监控和管理系统：实现资源自动清理和监控机制"""
import os
import threading
import time
import gc
from datetime import datetime

# 尝试导入psutil，如果没有安装则使用替代方案
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    import platform
    
    def _get_memory_percent():
        """在没有psutil的情况下估算内存使用率"""
        try:
            if platform.system() == "Windows":
                import subprocess
                result = subprocess.run(['wmic', 'OS', 'get', 'FreePhysicalMemory', '/value'], 
                                      capture_output=True, text=True, check=True)
                free_kb = float([line for line in result.stdout.split('\n') if 'FreePhysicalMemory=' in line][0]
                              .replace('FreePhysicalMemory=', '').strip())
                result_total = subprocess.run(['wmic', 'OS', 'get', 'TotalVisibleMemorySize', '/value'], 
                                          capture_output=True, text=True, check=True)
                total_kb = float([line for line in result_total.stdout.split('\n') if 'TotalVisibleMemorySize=' in line][0]
                                .replace('TotalVisibleMemorySize=', '').strip())
                return (1 - free_kb / total_kb) * 100
            else:
                # Linux/Mac 系统
                with open('/proc/meminfo') as f:
                    meminfo = f.read()
                meminfo = meminfo.split('\n')
                total_mem = int(meminfo[0].split()[1]) * 1024
                free_mem = int(meminfo[1].split()[1]) * 1024
                return (1 - free_mem / total_mem) * 100
        except:
            return 0  # 无法获取时返回0
    
    def _get_process_memory_mb():
        """获取当前进程内存使用(MB)"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except:
            return 0  # 无法获取时返回0
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from collections import defaultdict, deque
import logging
import weakref
from pathlib import Path

from src.config import setup_logger

logger = setup_logger("resource_monitor")


@dataclass
class ResourceMetrics:
    """资源指标数据类"""
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    disk_percent: float
    timestamp: datetime


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    response_time_ms: float
    throughput_per_sec: float
    error_rate: float
    timestamp: datetime


class ResourceTracker:
    """资源跟踪器 - 跟踪和清理未使用的资源"""
    
    def __init__(self):
        self._tracked_files = weakref.WeakSet()
        self._tracked_objects = weakref.WeakSet()
        self._file_handles = {}  # path -> (handle, open_time)
        self._max_age_seconds = 3600  # 1小时
        self._cleanup_interval = 300  # 5分钟清理一次
    
    def track_file(self, file_path: str):
        """跟踪文件资源"""
        self._tracked_files.add(file_path)
    
    def track_object(self, obj):
        """跟踪对象资源"""
        self._tracked_objects.add(obj)
    
    def register_file_handle(self, path: str, handle):
        """注册文件句柄"""
        self._file_handles[path] = (handle, time.time())
    
    def unregister_file_handle(self, path: str):
        """注销文件句柄"""
        if path in self._file_handles:
            del self._file_handles[path]
    
    def cleanup_resources(self):
        """清理过期资源"""
        current_time = time.time()
        
        # 清理过期的文件句柄
        expired_handles = []
        for path, (handle, open_time) in self._file_handles.items():
            if current_time - open_time > self._max_age_seconds:
                expired_handles.append(path)
        
        for path in expired_handles:
            handle, _ = self._file_handles[path]
            try:
                if hasattr(handle, 'close') and not handle.closed:
                    handle.close()
                    logger.warning(f"已关闭过期文件句柄: {path}")
            except Exception as e:
                logger.error(f"关闭文件句柄失败 {path}: {e}")
            del self._file_handles[path]
        
        # 强制垃圾回收
        collected = gc.collect()
        if collected > 0:
            logger.info(f"垃圾回收清理了 {collected} 个对象")


class HealthMonitor:
    """系统健康度监控器"""
    
    def __init__(self, history_size: int = 100):
        self.metrics_history = deque(maxlen=history_size)
        self.performance_history = deque(maxlen=history_size)
        self.resource_tracker = ResourceTracker()
        self._monitoring = False
        self._monitor_thread = None
        
        # 阈值配置
        self.cpu_threshold = 80.0  # CPU使用率阈值
        self.memory_threshold = 85.0  # 内存使用率阈值
        self.disk_threshold = 90.0  # 磁盘使用率阈值
        
        # 初始化进程对象（如果psutil可用）
        if PSUTIL_AVAILABLE:
            self.process = psutil.Process()
        else:
            self.process = None
    
    def start_monitoring(self, interval: float = 5.0):
        """开始监控"""
        if not self._monitoring:
            self._monitoring = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, 
                args=(interval,),
                daemon=True
            )
            self._monitor_thread.start()
            logger.info("系统健康监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
            logger.info("系统健康监控已停止")
    
    def _monitor_loop(self, interval: float):
        """监控循环"""
        while self._monitoring:
            try:
                metrics = self._collect_metrics()
                self.metrics_history.append(metrics)
                
                # 检查是否超过阈值
                self._check_thresholds(metrics)
                
                # 执行资源清理
                self.resource_tracker.cleanup_resources()
                
                time.sleep(interval)
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                time.sleep(interval)
    
    def _collect_metrics(self) -> ResourceMetrics:
        """收集系统资源指标"""
        try:
            if PSUTIL_AVAILABLE:
                cpu_percent = self.process.cpu_percent() if self.process else 0
                if self.process:
                    memory_info = self.process.memory_info()
                    memory_mb = memory_info.rss / 1024 / 1024
                else:
                    memory_mb = 0
                
                # 获取系统整体内存使用率
                system_memory = psutil.virtual_memory()
                memory_percent = system_memory.percent
                
                # 获取磁盘使用率
                disk_usage = psutil.disk_usage('.')
                disk_percent = (disk_usage.used / disk_usage.total) * 100
            else:
                # 没有psutil时的备选方案
                cpu_percent = 0  # 无法获取CPU使用率
                memory_mb = _get_process_memory_mb() if 'get_process_memory_mb' in globals() else 0
                memory_percent = _get_memory_percent() if 'get_memory_percent' in globals() else 0
                
                # 获取磁盘使用率
                import shutil
                total, used, free = shutil.disk_usage('.')
                disk_percent = (used / total) * 100
            
            return ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_mb,
                disk_percent=disk_percent,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"收集指标失败: {e}")
            return ResourceMetrics(0, 0, 0, 0, datetime.now())
    
    def _check_thresholds(self, metrics: ResourceMetrics):
        """检查指标是否超过阈值"""
        alerts = []
        
        if metrics.cpu_percent > self.cpu_threshold:
            alerts.append(f"CPU使用率过高: {metrics.cpu_percent:.1f}% > {self.cpu_threshold}%")
        
        if metrics.memory_percent > self.memory_threshold:
            alerts.append(f"内存使用率过高: {metrics.memory_percent:.1f}% > {self.memory_threshold}%")
        
        if metrics.disk_percent > self.disk_threshold:
            alerts.append(f"磁盘使用率过高: {metrics.disk_percent:.1f}% > {self.disk_threshold}%")
        
        if alerts:
            for alert in alerts:
                logger.warning(alert)
    
    def get_current_health(self) -> Dict[str, float]:
        """获取当前健康状态"""
        if self.metrics_history:
            latest = self.metrics_history[-1]
            return {
                'cpu_percent': latest.cpu_percent,
                'memory_percent': latest.memory_percent,
                'memory_used_mb': latest.memory_used_mb,
                'disk_percent': latest.disk_percent,
                'timestamp': latest.timestamp.isoformat()
            }
        return {}
    
    def get_average_metrics(self, minutes: int = 5) -> Dict[str, float]:
        """获取过去指定分钟的平均指标"""
        cutoff_time = datetime.now().timestamp() - (minutes * 60)
        
        recent_metrics = [
            m for m in self.metrics_history 
            if (datetime.now() - m.timestamp).total_seconds() <= minutes * 60
        ]
        
        if not recent_metrics:
            return {}
        
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_memory = sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
        avg_disk = sum(m.disk_percent for m in recent_metrics) / len(recent_metrics)
        
        return {
            'avg_cpu_percent': avg_cpu,
            'avg_memory_percent': avg_memory,
            'avg_disk_percent': avg_disk,
            'sample_count': len(recent_metrics)
        }


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, history_size: int = 1000):
        self.response_times = deque(maxlen=history_size)
        self.throughput_counter = 0
        self.error_counter = 0
        self.total_requests = 0
        self._lock = threading.Lock()
        self._start_time = time.time()
    
    def record_request(self, response_time_ms: float, success: bool = True):
        """记录请求"""
        with self._lock:
            self.response_times.append(response_time_ms)
            self.total_requests += 1
            if not success:
                self.error_counter += 1
    
    def increment_throughput(self):
        """增加吞吐量计数"""
        with self._lock:
            self.throughput_counter += 1
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """获取性能指标"""
        with self._lock:
            elapsed_time = time.time() - self._start_time
            throughput = self.throughput_counter / elapsed_time if elapsed_time > 0 else 0
            error_rate = (self.error_counter / self.total_requests * 100) if self.total_requests > 0 else 0
            
            if self.response_times:
                avg_response_time = sum(self.response_times) / len(self.response_times)
                p95_response_time = sorted(self.response_times)[int(len(self.response_times) * 0.95)]
                p99_response_time = sorted(self.response_times)[int(len(self.response_times) * 0.99)]
            else:
                avg_response_time = p95_response_time = p99_response_time = 0
            
            return {
                'avg_response_time_ms': avg_response_time,
                'p95_response_time_ms': p95_response_time,
                'p99_response_time_ms': p99_response_time,
                'throughput_per_sec': throughput,
                'error_rate_percent': error_rate,
                'total_requests': self.total_requests
            }


# 全局监控实例
health_monitor = HealthMonitor()
performance_monitor = PerformanceMonitor()


def init_resource_monitoring():
    """初始化资源监控"""
    health_monitor.start_monitoring(interval=5.0)
    logger.info("资源监控系统已初始化")


def cleanup_resources():
    """手动清理资源"""
    health_monitor.resource_tracker.cleanup_resources()
    logger.info("资源清理完成")


def get_system_health():
    """获取系统健康状态"""
    return {
        'current_health': health_monitor.get_current_health(),
        'average_metrics': health_monitor.get_average_metrics(minutes=5),
        'performance_metrics': performance_monitor.get_performance_metrics()
    }


# 在模块加载时初始化监控
init_resource_monitoring()