"""作业注册表与 /api/jobs 接口测试（不依赖外部服务）"""
import allure
import pytest

from src.core.job_registry import JOBS, JobRegistry


@allure.feature("作业模型")
@allure.story("作业注册表")
def test_job_registry_lifecycle():
    reg = JobRegistry()
    job = reg.create("unit", "单测作业", total=4)
    assert reg.get(job.id).status == "running"

    reg.update(job.id, done=2, message="进行中")
    snap = reg.get(job.id).snapshot()
    assert snap["done"] == 2 and snap["percent"] == 50.0

    reg.cancel(job.id)
    assert reg.is_cancelled(job.id) is True

    reg.finish(job.id, "cancelled", "用户停止")
    assert reg.get(job.id).status == "cancelled"
    assert reg.get(job.id).message == "用户停止"


@allure.feature("作业模型")
@allure.story("作业注册表")
def test_job_registry_list_and_missing():
    reg = JobRegistry()
    assert reg.get("nope") is None
    assert reg.update("nope", done=1) is None
    assert reg.finish("nope") is None
    assert reg.cancel("nope") is None

    a = reg.create("unit", "A")
    b = reg.create("unit", "B")
    titles = [j["title"] for j in reg.list()]
    assert titles[0] == "B" and titles[1] == "A"     # 新→旧


@allure.feature("作业模型")
@allure.story("作业接口")
def test_jobs_api():
    from fastapi.testclient import TestClient
    from src.api.app import create_app

    client = TestClient(create_app())
    body = client.get("/api/jobs").json()
    assert body["ok"] is True
    assert isinstance(body["data"]["jobs"], list)

    miss = client.get("/api/jobs/not-exist").json()
    assert miss["ok"] is False

    stop = client.post("/api/jobs/not-exist/stop").json()
    assert stop["ok"] is False
