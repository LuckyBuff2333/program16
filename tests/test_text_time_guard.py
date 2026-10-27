"""文本提取方向校验：抓到的评论/字段时间不能晚于日志抓包时间"""
from datetime import datetime

import pytest

from src.clients import jira_client as jc


@pytest.fixture
def issue():
    return {"fields": {"attachment": [
        {"filename": "gmlogger_2026_10_27_15_23_55.tar.gz",
         "content": "https://example.invalid/log.tar.gz", "size": 1},
    ]}}


def test_text_time_after_capture_falls_back_to_log_name(monkeypatch, issue):
    monkeypatch.setattr(jc, "_extract_trigger_time_from_issue_impl",
                        lambda *a, **k: ("2026-10-27 21:12:00", "评论"))
    time_str, source = jc.extract_trigger_time_from_issue(issue, return_source=True)
    assert time_str == "2026-10-27 15:23:55"
    assert source == "附件名(抓包时间兜底)"


def test_text_time_before_capture_kept(monkeypatch, issue):
    monkeypatch.setattr(jc, "_extract_trigger_time_from_issue_impl",
                        lambda *a, **k: ("2026-10-27 15:20:00", "评论"))
    time_str, source = jc.extract_trigger_time_from_issue(issue, return_source=True)
    assert time_str == "2026-10-27 15:20:00" and source == "评论"


def test_text_time_slightly_after_capture_kept(monkeypatch, issue):
    def fake_impl(issue, return_source=False, skip_attachment=False):
        return ("2026-10-27 15:27:00", "评论") if return_source else "2026-10-27 15:27:00"
    monkeypatch.setattr(jc, "_extract_trigger_time_from_issue_impl", fake_impl)
    assert jc.extract_trigger_time_from_issue(issue) == "2026-10-27 15:27:00"


def test_no_log_attachment_no_check(monkeypatch):
    def fake_impl(issue, return_source=False, skip_attachment=False):
        return ("2026-10-27 21:12:00", "评论") if return_source else "2026-10-27 21:12:00"
    monkeypatch.setattr(jc, "_extract_trigger_time_from_issue_impl", fake_impl)
    issue = {"fields": {"attachment": [{"filename": "20261027-170955.mp4"}]}}
    assert jc.extract_trigger_time_from_issue(issue) == "2026-10-27 21:12:00"


def test_skip_attachment_rejects_without_fallback(monkeypatch, issue):
    monkeypatch.setattr(jc, "_extract_trigger_time_from_issue_impl",
                        lambda *a, **k: ("2026-10-27 21:12:00", "评论"))
    time_str, source = jc.extract_trigger_time_from_issue(issue, return_source=True, skip_attachment=True)
    assert time_str == "" and source == "rejected_after_capture"


def test_get_log_capture_time_variants():
    for name in ("GMLog_20261027_152355.7z",
                 "pataclogger_2026_10_27_17_15_0.part01.rar",
                 "784da062_20261027_173855.7z"):
        issue = {"fields": {"attachment": [{"filename": name}]}}
        assert jc.get_log_capture_time(issue) is not None
    assert jc.get_log_capture_time({"fields": {"attachment": [{"filename": "20261027-170955.mp4"}]}}) is None
