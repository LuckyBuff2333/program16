"""自检列（时间来源/参考时间/时间差秒/窗口命中/状态）在各类写入路径都要有值"""
from datetime import datetime

import pytest

from src.services import trigger_ops as t


def test_resolve_ref_time_uses_cache(monkeypatch):
    t._TRIGGER_TIME_REF_CACHE.clear()
    t.remember_ref_time("VCU-7001", "2026-10-27 15:23:55")
    assert t._resolve_ref_time("VCU-7001") == "2026-10-27 15:23:55"


def test_resolve_ref_time_fetches_jira_when_cache_miss(monkeypatch):
    t._TRIGGER_TIME_REF_CACHE.clear()
    from src.clients import jira_client
    from src.services import server_legacy

    monkeypatch.setattr(jira_client, "fetch_issue",
                        lambda k: {"fields": {"attachment": [{"filename": "gmlogger_2026_10_27_17_15_0.tar.gz"}]}})
    monkeypatch.setattr(server_legacy, "_diag_gmlogger_times",
                        lambda atts: [("2026-10-27 17:15:00", datetime(2026, 10, 27, 17, 15))])
    assert t._resolve_ref_time("VCU-7002") == "2026-10-27 17:15:00"
    # 解析结果会进缓存，第二次不再查 Jira
    assert t._lookup_ref("VCU-7002") == "2026-10-27 17:15:00"


def test_resolve_ref_time_returns_empty_on_error(monkeypatch):
    t._TRIGGER_TIME_REF_CACHE.clear()
    from src.clients import jira_client

    def boom(k):
        raise RuntimeError("jira down")

    monkeypatch.setattr(jira_client, "fetch_issue", boom)
    assert t._resolve_ref_time("VCU-7003") == ""


def test_save_defaults_source_and_passes_ref(monkeypatch):
    captured = {}

    def fake_batch(items, sources=None, ref_times=None):
        captured["items"] = items
        captured["sources"] = sources
        captured["refs"] = ref_times
        return True

    monkeypatch.setattr(t, "_ensure_fields_once", lambda: None)
    monkeypatch.setattr(t, "_ensure_trigger_time_bugid_cache", lambda: None)
    monkeypatch.setattr(t, "_trigger_time_bugid_cache", {})
    monkeypatch.setattr(t, "_resolve_ref_time", lambda bugid, ref="": "2026-10-27 17:15:00")
    monkeypatch.setattr(t, "_batch_save_trigger_times_to_cloud", fake_batch)
    monkeypatch.setattr(t, "_save_trigger_time_to_csv", lambda b, v: None)

    t._save_trigger_time_to_cloud("VCU-7004", "2026-10-27 17:12:00")
    assert captured["sources"]["VCU-7004"] == "未标注"
    assert captured["refs"]["VCU-7004"] == "2026-10-27 17:15:00"


def test_save_keeps_explicit_source(monkeypatch):
    captured = {}

    def fake_batch(items, sources=None, ref_times=None):
        captured["sources"] = sources
        return True

    monkeypatch.setattr(t, "_ensure_fields_once", lambda: None)
    monkeypatch.setattr(t, "_ensure_trigger_time_bugid_cache", lambda: None)
    monkeypatch.setattr(t, "_trigger_time_bugid_cache", {})
    monkeypatch.setattr(t, "_resolve_ref_time", lambda bugid, ref="": "")
    monkeypatch.setattr(t, "_batch_save_trigger_times_to_cloud", fake_batch)
    monkeypatch.setattr(t, "_save_trigger_time_to_csv", lambda b, v: None)

    t._save_trigger_time_to_cloud("VCU-7005", "2026-10-27 17:12:00", source="时间对比(读取)")
    assert captured["sources"]["VCU-7005"] == "时间对比(读取)"
