"""P0-1/P0-2：触发时间自检与扩展列写入测试（不访问真实飞书）"""
import allure
import pytest

from src.services import trigger_ops as t


@allure.feature("触发时间自检")
@allure.story("自检分级")
def test_self_check_levels():
    """方向敏感：事件发生在抓包之前，早于抓包是正常现象"""
    same = t.self_check_trigger_time("2026-10-23 16:08:00", "2026-10-23 16:08:10")
    assert same["status"] == "正常" and same["window_hit"] == "是"

    # 早于抓包 2 分钟（真实场景中位早 156 秒）→ 正常
    early = t.self_check_trigger_time("2026-10-23 16:06:00", "2026-10-23 16:08:00")
    assert early["status"] == "正常" and early["window_hit"] == "否"

    # 早于抓包 30 分钟 → 待确认
    early_warn = t.self_check_trigger_time("2026-10-23 15:38:00", "2026-10-23 16:08:00")
    assert early_warn["status"] == "待确认"

    # 早于抓包 2 小时 → 不可用（可能日期/时钟错）
    far_early = t.self_check_trigger_time("2026-10-23 14:08:00", "2026-10-23 16:08:00")
    assert far_early["status"] == "不可用"

    # 晚于抓包 2 分钟 → 待确认（轻微时钟抖动，需人工看一眼）
    after = t.self_check_trigger_time("2026-10-23 16:10:00", "2026-10-23 16:08:00")
    assert after["status"] == "待确认" and after["window_hit"] == "否"

    # 晚于抓包 10 分钟 → 不可用（抓包后不可能再触发）
    after_far = t.self_check_trigger_time("2026-10-23 16:18:00", "2026-10-23 16:08:00")
    assert after_far["status"] == "不可用"

    none_ref = t.self_check_trigger_time("2026-10-23 16:08:00", "")
    assert none_ref["status"] == "无参考" and none_ref["diff_sec"] is None


@allure.feature("触发时间自检")
@allure.story("自检列")
def test_trigger_time_meta_fields():
    meta = t._trigger_time_meta("2026-10-23 16:08:00", "video_ocr", "2026-10-23 16:08:20")
    assert meta["时间来源"] == "video_ocr"
    assert meta["参考时间"] == "2026-10-23 16:08:20"
    assert meta["时间差秒"] == "20"
    assert meta["窗口命中"] == "是"
    assert meta["时间状态"] == "正常"


@allure.feature("触发时间自检")
@allure.story("参考时间登记")
def test_remember_ref_time():
    t._TRIGGER_TIME_REF_CACHE.clear()
    t.remember_ref_time("VCU-9001", "2026-10-23 16:08:20")
    assert t._lookup_ref("VCU-9001") == "2026-10-23 16:08:20"
    assert t._lookup_ref("VCU-9001", {"VCU-9001": "2026-01-01 00:00:00"}) == "2026-01-01 00:00:00"
    assert t._lookup_ref("VCU-none") == ""


@allure.feature("触发时间自检")
@allure.story("写表字段")
def test_batch_save_includes_meta(monkeypatch):
    from src.clients import feishu_client

    captured = {}

    def fake_update(app_token, table_id, recs):
        captured["update"] = (app_token, table_id, recs)

    monkeypatch.setattr(feishu_client, "update_bitable_records", fake_update)
    monkeypatch.setattr(t, "_ensure_fields_once", lambda: None)
    monkeypatch.setattr(t, "_get_trigger_time_table_cfg", lambda: ("app", ["tbl"]))
    monkeypatch.setattr(t, "_bitable_bulk_cache", {})

    t._trigger_time_bugid_cache.clear()
    t._trigger_time_bugid_cache["VCU-9002"] = ("tbl", "rec-1", "旧时间")
    t._TRIGGER_TIME_REF_CACHE.clear()
    t.remember_ref_time("VCU-9002", "2026-10-23 16:08:20")

    ok = t._batch_save_trigger_times_to_cloud({"VCU-9002": "2026-10-23 16:08:00"}, {"VCU-9002": "视频提取"})
    assert ok is True
    fields = captured["update"][2][0]["fields"]
    assert fields["触发时间"] == "2026-10-23 16:08:00"
    assert fields["时间来源"] == "视频提取"
    assert fields["时间差秒"] == "20"
    assert fields["窗口命中"] == "是"
    assert fields["时间状态"] == "正常"


@allure.feature("触发时间自检")
@allure.story("字段补齐")
def test_ensure_fields_idempotent(monkeypatch):
    from src.clients import feishu_client

    created = []
    monkeypatch.setattr(feishu_client, "list_bitable_fields",
                        lambda app, tid: [{"field_name": "jira号"}, {"field_name": "触发时间"},
                                          {"field_name": "提取时间"}, {"field_name": "时间来源"}])
    monkeypatch.setattr(feishu_client, "create_bitable_field",
                        lambda app, tid, name, ftype=1: created.append(name) or True)
    monkeypatch.setattr(t, "_get_trigger_time_table_cfg", lambda: ("app", ["tbl"]))
    t._TRIGGER_TIME_FIELDS_ENSURED["done"] = False
    t.ensure_trigger_time_fields()
    assert "时间来源" not in created          # 已存在，不重复创建
    for name in ("参考时间", "时间差秒", "窗口命中", "时间状态"):
        assert name in created


@allure.feature("触发时间自检")
@allure.story("分析前自检")
def test_pre_analysis_check(monkeypatch):
    from src.services import server_legacy
    from src import pipeline

    atts = [{"filename": "gmlogger_2026_10_23_16_08_20.rar"}]
    monkeypatch.setattr(server_legacy, "_diag_gmlogger_times",
                        lambda attachments: [("2026-10-23 16:08:20", "gmlogger")])
    issue = {"fields": {"attachment": atts}}

    ok = pipeline._time_check_before_analysis(issue, "2026-10-23 16:08:10")
    assert ok["status"] == "正常" and ok["diff_sec"] == 10

    bad = pipeline._time_check_before_analysis(issue, "2026-10-23 20:00:00")
    assert bad["status"] == "不可用"
