"""ADP 附件过滤：压缩包/日志/分卷类型覆盖测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.adp_ops import _is_valid_attachment


def _ok(name):
    return _is_valid_attachment({"filename": name, "downloadUrl": "http://x"})


def test_plain_archives():
    for n in ("gmlogger.7z", "log.zip", "log.rar", "log.tar", "log.tar.gz", "log.gz",
              "a.tar.bz2", "a.tar.xz", "a.tar.zst", "a.zst", "a.log", "a.txt"):
        assert _ok(n), n


def test_numeric_volumes():
    for n in ("gmlogger.7z.001", "gmlogger.7z.002", "log.zip.001", "log.tar.gz.001",
              "a.001", "a.002", "a.log.001"):
        assert _ok(n), n


def test_zip_old_volumes():
    for n in ("log.z01", "log.z02", "log.z99"):
        assert _ok(n), n


def test_rar_part_volumes():
    for n in ("log.part1.rar", "log.part01.rar", "log.part999.rar", "log.r00", "log.r01"):
        assert _ok(n), n


def test_non_log_files_rejected():
    for n in ("screenshot.png", "video.mp4", "readme.md", "image.jpg"):
        assert not _ok(n), n


def test_requires_download_url():
    assert not _is_valid_attachment({"filename": "gmlogger.7z", "downloadUrl": ""})
