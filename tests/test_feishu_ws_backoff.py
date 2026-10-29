"""飞书长连接：DNS 预检与退避辅助函数单测"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.feishu_client import _ws_host, _next_backoff, _dns_ok, _ws_domain


def test_ws_host_from_domain():
    assert _ws_host("https://open.feishu.cn") == "open.feishu.cn"
    assert _ws_host("https://open.larksuite.com/") == "open.larksuite.com"


def test_backoff_progression():
    b = 5
    seq = [b]
    for _ in range(4):
        b = _next_backoff(b)
        seq.append(b)
    assert seq == [5, 10, 20, 40, 60]


def test_backoff_capped_and_min():
    assert _next_backoff(60) == 60
    assert _next_backoff(0) == 5


def test_dns_ok_localhost():
    assert _dns_ok("localhost") is True


def test_dns_fail_invalid_host():
    assert _dns_ok("no-such-host.invalid") is False


def test_ws_domain_default():
    d = _ws_domain()
    assert d.startswith("http")
