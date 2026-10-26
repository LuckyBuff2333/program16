"""跑批作业注册表：给长时间运行的批量任务一个 id、状态和停止句柄

目标：让「正在跑什么、跑到哪、能不能停」可查询，而不是只能靠前端一次性 SSE 连接。
- 内存态，不持久化（重启后清空；要跨重启恢复再落 SQLite）
- 每个作业自带 stop_event，停止只影响自己，不会串台
"""
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    type: str
    title: str
    status: str = "running"          # running / done / failed / cancelled
    total: int = 0
    done: int = 0
    message: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict:
        elapsed = round(time.time() - self.created_at, 1)
        percent = round(self.done * 100.0 / self.total, 1) if self.total else 0.0
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "percent": percent,
            "elapsed_sec": elapsed,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobRegistry:
    """线程安全的作业注册表（保留最近 max_jobs 个，自动淘汰最旧的已完成作业）"""

    def __init__(self, max_jobs: int = 50):
        self._lock = threading.Lock()
        self._jobs: dict = {}
        self._order: list = []
        self._max_jobs = max_jobs

    def create(self, job_type: str, title: str, total: int = 0) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], type=job_type, title=title, total=total)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._evict_locked()
        return job

    def update(self, job_id: str, **kwargs) -> Job:
        """更新进度：done/total/message 等；status 只允许 running"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for k, v in kwargs.items():
                if hasattr(job, k) and k not in ("id", "stop_event", "created_at"):
                    setattr(job, k, v)
            job.updated_at = time.time()
            return job

    def finish(self, job_id: str, status: str = "done", message: str = "", error: str = ""):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status == "running" or status in ("done", "failed", "cancelled"):
                job.status = status
            job.message = message or job.message
            job.error = error
            job.updated_at = time.time()
            return job

    def get(self, job_id: str):
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str):
        """置位停止事件；线程里检查 job.stop_event / is_cancelled()"""
        job = self.get(job_id)
        if not job:
            return None
        job.stop_event.set()
        self.update(job_id, message="已请求停止")
        return job

    def is_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        return bool(job and job.stop_event.is_set())

    def list(self, limit: int = 20) -> list:
        with self._lock:
            ids = list(reversed(self._order))[:limit]
            return [self._jobs[i].snapshot() for i in ids if i in self._jobs]

    def _evict_locked(self):
        while len(self._order) > self._max_jobs:
            old = self._order.pop(0)
            job = self._jobs.get(old)
            if job and job.status == "running":
                self._order.append(old)   # 运行中的不淘汰
                return
            self._jobs.pop(old, None)


JOBS = JobRegistry()
