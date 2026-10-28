"""表格时间对比判定：_judge_compare_time 单测"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.routes.trigger import _judge_compare_time, _parse_any_time


def _dt(*args):
    return datetime(*args)


def test_normal_within_5min():
    judge, _ = _judge_compare_time(
        "2026-05-20 13:15:00", "2026/05/20 13:20",
        _dt(2026, 5, 20, 13, 20), _dt(2026, 5, 20, 17, 46))
    assert judge == "正常"


def test_whole_day_offset_marks_date_uncertain():
    judge, reason = _judge_compare_time(
        "2026-05-19 13:20:00", "2026/05/20 13:20",
        _dt(2026, 5, 20, 13, 20), _dt(2026, 5, 20, 17, 46))
    assert judge == "日期待确认"
    assert "1 天" in reason


def test_extract_after_capture_is_extract_error():
    judge, _ = _judge_compare_time(
        "2026-05-21 13:33:00", "2026/05/20 13:34",
        _dt(2026, 5, 20, 13, 34), _dt(2026, 5, 21, 10, 28))
    assert judge == "提取错误"


def test_extract_too_early_before_capture_is_extract_error():
    judge, _ = _judge_compare_time(
        "2026-04-16 16:25:40", "2025/10/31 16:32",
        _dt(2026, 4, 16, 17, 41), _dt(2026, 4, 30, 15, 37))
    assert judge == "提取错误"


def test_only_date_00_is_extract_error():
    judge, reason = _judge_compare_time(
        "2026-06-17 00:00:00", "2026/06/17 14:34",
        None, _dt(2026, 6, 17, 14, 41))
    assert judge == "提取错误"
    assert "时分" in reason


def test_table_after_created_is_table_error():
    judge, _ = _judge_compare_time(
        "2026-04-18 16:20:00", "2026/07/30 00:33",
        _dt(2026, 4, 18, 16, 18), _dt(2026, 4, 18, 16, 23))
    assert judge == "表格错误"


def test_both_wrong():
    judge, _ = _judge_compare_time(
        "2026-04-21 10:56:12", "2026/04/24 10:56",
        _dt(2026, 4, 22, 15, 34), _dt(2026, 4, 22, 15, 44))
    assert judge in ("两边都错", "提取错误")


def test_parse_any_time_formats():
    assert _parse_any_time("2026/05/20 13:20") == datetime(2026, 5, 20, 13, 20)
    assert _parse_any_time("2026-05-20 13:20:00") == datetime(2026, 5, 20, 13, 20)
    assert _parse_any_time("") is None
