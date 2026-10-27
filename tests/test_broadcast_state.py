"""播报跨机器状态测试：不联网，用 fake feishu_client 验证抢占/去重/回退"""
from datetime import datetime, timedelta

import pytest

import src.services.broadcast_state as bs


class FakeClient:
    def __init__(self):
        self.records = []
        self.seq = 1000
        self.fail = False
        self.extra_on_create = None

    def _check(self):
        if self.fail:
            raise RuntimeError("cloud down")

    def list_bitable_tables(self, app_token):
        self._check()
        return [{"name": "播报状态", "table_id": "tblS"}]

    def list_bitable_records(self, app_token, table_id):
        self._check()
        return [{"record_id": r["record_id"], "fields": dict(r["fields"])} for r in self.records]

    def batch_create_records(self, app_token, table_id, records):
        self._check()
        out = []
        for rec in records:
            self.seq += 1
            rid = f"rec{self.seq:04d}"
            self.records.append({"record_id": rid, "fields": dict(rec["fields"])})
            out.append({"record_id": rid})
        if self.extra_on_create:
            extra = self.extra_on_create
            self.extra_on_create = None
            # 模拟另一台机器在并发窗口内抢先写入（record_id 更小）
            self.records.append({"record_id": "rec0001", "fields": dict(extra)})
        return {"records": out}

    def batch_delete_records(self, app_token, table_id, ids):
        self._check()
        self.records = [r for r in self.records if r["record_id"] not in ids]
        return {"deleted": len(ids)}

    def update_bitable_records(self, app_token, table_id, records):
        self._check()
        by_id = {r["record_id"]: r for r in self.records}
        for rec in records:
            r = by_id.get(rec["record_id"])
            if r:
                r["fields"].update(rec["fields"])
        return {"records": records}


@pytest.fixture
def fake(monkeypatch):
    f = FakeClient()
    monkeypatch.setattr(bs, "feishu_client", f)
    monkeypatch.setattr(bs, "load_config", lambda: {
        "feishu_bitable": {"app_token": "app"},
        "daily_broadcast": {"state_table_id": "tblS"},
    })
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    bs._TABLE_CACHE.update({"app_token": "", "table_id": "", "ts": 0})
    return f


def test_claim_then_second_machine_sees_exists(fake):
    state, rec = bs.claim("oc_1", "2026-10-27", "17:00")
    assert state == "claimed" and rec
    state2, rec2 = bs.claim("oc_1", "2026-10-27", "17:00")
    assert state2 == "exists" and rec2 == rec


def test_finish_marks_success(fake):
    _, rec = bs.claim("oc_1", "2026-10-27", "17:00")
    assert bs.finish(rec, True, "定时播报") is True
    st = bs.get_state("oc_1", "2026-10-27")
    assert st["status"] == "success" and st["detail"] == "定时播报"


def test_record_result_upserts(fake):
    assert bs.record_result("oc_2", "2026-10-26", True, "手动") is True
    st = bs.get_state("oc_2", "2026-10-26")
    assert st["status"] == "success"
    # 再次记录只更新同一条，不新增
    assert bs.record_result("oc_2", "2026-10-26", False, "失败") is True
    assert len([r for r in fake.records if r["fields"].get("群ID") == "oc_2"]) == 1


def test_cloud_failure_falls_back(fake):
    fake.fail = True
    state, rec = bs.claim("oc_3", "2026-10-27", "17:00")
    assert state == "unavailable" and rec == ""


def test_stale_claim_can_be_taken_over(fake):
    old = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    fake.records.append({"record_id": "rec0005", "fields": {
        "群ID": "oc_4", "播报日期": "2026-10-27", "状态": "claiming",
        "机器": "other", "更新时间": old}})
    state, rec = bs.claim("oc_4", "2026-10-27", "17:00")
    assert state == "claimed" and rec == "rec0005"


def test_race_loser_deletes_own_record(fake):
    fake.extra_on_create = {"群ID": "oc_5", "播报日期": "2026-10-27",
                            "状态": "claiming", "机器": "other",
                            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    state, rec = bs.claim("oc_5", "2026-10-27", "17:00")
    assert state == "exists" and rec == "rec0001"
    # 自己那条已被删除，只剩胜者
    assert len(fake.records) == 1
