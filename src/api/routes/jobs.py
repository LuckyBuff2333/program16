"""跑批作业状态查询与停止：GET /api/jobs、GET /api/jobs/{job_id}、POST /api/jobs/{job_id}/stop"""
import asyncio
import threading

from fastapi import APIRouter

from src.api.routes.shared import ok as _ok, fail as _fail
from src.core.job_registry import JOBS
from src.schemas.common import ApiResponse

router = APIRouter()


def job_stream(job, gen_factory, flow_stop_event=None):
    """把 SSE 生成器包一层作业生命周期（不改动生成器内部）

    - 正常结束 → done；抛异常 → failed；被 cancel → cancelled
    - 传 flow_stop_event 时，作业被取消会同步置位该流程的停止事件
    """
    if flow_stop_event is not None:
        def _bridge():
            import time as _t
            while job.status == "running":
                if job.stop_event.is_set():
                    flow_stop_event.set()
                    return
                _t.sleep(0.5)
        threading.Thread(target=_bridge, daemon=True).start()

    async def _wrapped():
        err = ""
        try:
            async for chunk in gen_factory():
                yield chunk
        except asyncio.CancelledError:      # 客户端断开
            JOBS.finish(job.id, "cancelled", "客户端断开")
            raise
        except Exception as e:              # noqa: BLE001
            err = str(e)[:200]
            JOBS.finish(job.id, "failed", error=err)
            raise
        finally:
            if job.status == "running":
                status = "cancelled" if job.stop_event.is_set() else ("failed" if err else "done")
                JOBS.finish(job.id, status, error=err)

    return _wrapped()


@router.get("/api/jobs", response_model=ApiResponse)
def list_jobs(limit: int = 20):
    """列出最近的后台作业（跑批任务的 id/状态/进度），新→旧"""
    jobs = JOBS.list(limit)
    return _ok({"jobs": jobs}, f"共 {len(jobs)} 个作业")


@router.get("/api/jobs/{job_id}", response_model=ApiResponse)
def get_job(job_id: str):
    """查询单个作业的状态与进度"""
    job = JOBS.get(job_id)
    if not job:
        return _fail(f"作业不存在: {job_id}")
    return _ok(job.snapshot())


@router.post("/api/jobs/{job_id}/stop", response_model=ApiResponse)
def stop_job(job_id: str):
    """请求停止某个作业（只置位它自己的停止事件，不影响其它作业）"""
    job = JOBS.cancel(job_id)
    if not job:
        return _fail(f"作业不存在: {job_id}")
    return _ok(job.snapshot(), f"已请求停止作业 {job_id}")
