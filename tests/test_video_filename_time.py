"""视频文件名时间回退解析测试。"""
from src.services.server_legacy import _parse_video_filename_time


def test_mmdd_suffix_not_parsed_as_time():
    # -1008 是 10 月 08 日，不能再被当成 10:08
    assert _parse_video_filename_time("VCU-553562-1008.mp4") == ""
    assert _parse_video_filename_time("VCU-553561-1008.mp4") == ""


def test_unambiguous_compact_time_still_parsed():
    # 14 不可能是月份，仍是 14:30
    assert _parse_video_filename_time("video-1430.mp4") == "14:30:00"


def test_full_datetime_time_not_regressed():
    assert _parse_video_filename_time("20260928-163807.mp4") == "16:38:07"


def test_mmdd_without_date_position_not_removed():
    # 规则只针对文件名末尾的 -/_MMDD；中间片段不强行删除
    assert _parse_video_filename_time("video-1008-2.mp4") == "10:08:00"
