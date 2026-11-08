"""通用 HTTP 客户端封装：httpx 连接池 + tenacity 指数退避重试"""
import time
import warnings

import httpx
import urllib3
from tenacity import (
    retry, stop_after_attempt, wait_exponential, wait_random,
    retry_if_exception, before_sleep_log,
)

from src.config import setup_logger

logger = setup_logger("http")

# 抑制 verify=False 产生的 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 默认重试次数与超时
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 60
# 连接超时（TCP 握手阶段），不受 read timeout 影响
CONNECT_TIMEOUT = 30

# ── 全局连接池：复用 TCP 连接，避免每次请求重新 TLS 握手 ──
_POOL_CLIENT: httpx.Client = None


def _get_pool_client() -> httpx.Client:
    """懒加载全局 httpx.Client（线程安全，连接池复用）"""
    global _POOL_CLIENT
    if _POOL_CLIENT is None or _POOL_CLIENT.is_closed:
        _POOL_CLIENT = httpx.Client(
            verify=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=CONNECT_TIMEOUT),
        )
    return _POOL_CLIENT


def _is_https(url: str) -> bool:
    """判断 URL 是否为 HTTPS"""
    return url.startswith("https://")


def _get_verify(url: str) -> bool:
    """获取 SSL 验证设置：HTTPS 请求跳过证书验证（内网企业代理会替换证书）"""
    return False if _is_https(url) else True


def _should_retry(exc: BaseException) -> bool:
    """仅对网络传输错误和服务端 5xx 错误重试，4xx 客户端错误不重试"""
    if _http_cancelled():
        return False
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


_HTTP_CANCEL_CHECK = None


def set_http_cancel_check(fn):
    """设置全局 HTTP 取消检查（返回 True 时立即停止请求/重试）"""
    global _HTTP_CANCEL_CHECK
    _HTTP_CANCEL_CHECK = fn


def _http_cancelled() -> bool:
    try:
        return bool(_HTTP_CANCEL_CHECK and _HTTP_CANCEL_CHECK())
    except Exception:
        return False


@retry(
    stop=stop_after_attempt(DEFAULT_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 2),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, 20),
    reraise=True,
)
def http_post(url: str, payload: dict, timeout: int = DEFAULT_TIMEOUT,
              headers: dict = None) -> dict:
    """POST 请求并返回 JSON，失败时 tenacity 指数退避重试（仅重试网络错误和 5xx）"""
    if _http_cancelled():
        raise RuntimeError("操作已停止")
    logger.info("POST %s", url)
    client = _get_pool_client()
    response = client.post(url, json=payload, timeout=timeout, headers=headers)
    response.raise_for_status()
    return response.json()


@retry(
    stop=stop_after_attempt(DEFAULT_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 2),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, 20),
    reraise=True,
)
def http_get(url: str, params: dict = None, timeout: int = DEFAULT_TIMEOUT,
             auth: tuple = None, headers: dict = None) -> dict:
    """GET 请求并返回 JSON，失败时 tenacity 指数退避重试（仅重试网络错误和 5xx）"""
    if _http_cancelled():
        raise RuntimeError("操作已停止")
    logger.info("GET %s", url)
    client = _get_pool_client()
    response = client.get(url, params=params, timeout=timeout, auth=auth, headers=headers)
    response.raise_for_status()
    return response.json()


def cancellable_sleep(total_seconds, cancel_check=None, interval=1):
    """可取消的 sleep：每秒检查 cancel_check，收到取消信号立即返回 True

    :param total_seconds: 总等待秒数
    :param cancel_check: 取消回调，返回 True 表示需要取消
    :param interval: 检查间隔秒数
    :return: True 表示被取消，False 表示正常等待结束
    """
    waited = 0
    while waited < total_seconds:
        if cancel_check and cancel_check():
            return True
        time.sleep(min(interval, total_seconds - waited))
        waited += interval
    return False
