"""日志包文件名识别：GMLog_/pataclogger/哈希名 等也要能解析出抓包时间"""
from src.services.server_legacy import _diag_gmlogger_times


def test_common_gmlogger_name():
    times = _diag_gmlogger_times([{"filename": "gmlogger_2026_10_19_21_14_43.tar.gz"}])
    assert times and times[0][0] == "2026-10-19 21:14:43"


def test_gmlog_compact_name():
    times = _diag_gmlogger_times([{"filename": "GMLog_20261027_152355.7z"}])
    assert times and times[0][0] == "2026-10-27 15:23:55"


def test_pataclogger_split_volume():
    times = _diag_gmlogger_times([{"filename": "pataclogger_2026_10_27_17_15_0.part01.rar"}])
    assert times and times[0][0] == "2026-10-27 17:15:00"


def test_hash_prefixed_archive():
    times = _diag_gmlogger_times([{"filename": "784da062_20261027_173855.7z"}])
    assert times and times[0][0] == "2026-10-27 17:38:55"


def test_video_not_treated_as_log():
    assert _diag_gmlogger_times([{"filename": "20261027-170955.mp4"}]) == []


def test_no_timestamp_returns_empty():
    assert _diag_gmlogger_times([{"filename": "gmlogger.7z"}]) == []
