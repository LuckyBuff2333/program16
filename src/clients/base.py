"""通用 HTTP 客户端封装：httpx 连接池 + tenacity 指数退避重试"""
import time
import warnings

import httpx
import urllib3
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception, before_sleep_log,
)

from src.config import setup_logger

logger = setup_logger("http")

# 抑制 verify=False 产生的 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 默认重试次数与超时
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 30
# 连接超时（TCP 握手阶段），不受 read timeout 影响
CONNECT_TIMEOUT = 30


def _is_https(url: str) -> bool:
    """判断 URL 是否为 HTTPS"""
    return url.startswith("https://")


def _get_verify(url: str) -> bool:
    """获取 SSL 验证设置：HTTPS 请求跳过证书验证（内网企业代理会替换证书）"""
    return False if _is_https(url) else True


def _should_retry(exc: BaseException) -> bool:
    """仅对网络传输错误和服务端 5xx 错误重试，4xx 客户端错误不重试"""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


@retry(
    stop=stop_after_attempt(DEFAULT_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, 20),
    reraise=True,
)
def http_post(url: str, payload: dict, timeout: int = DEFAULT_TIMEOUT,
              headers: dict = None) -> dict:
    """POST 请求并返回 JSON，失败时 tenacity 指数退避重试（仅重试网络错误和 5xx）"""
    logger.info("POST %s", url)
    # 分离连接超时和读取超时：连接阶段最多等 CONNECT_TIMEOUT 秒，读取阶段使用 timeout 参数
    http_timeout = httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)
    # 内网环境企业 HTTPS 代理会替换证书，跳过 SSL 验证避免 CERTIFICATE_VERIFY_FAILED
    verify = _get_verify(url)
    response = httpx.post(url, json=payload, timeout=http_timeout, headers=headers, verify=verify)
    response.raise_for_status()
    return response.json()


@retry(
    stop=stop_after_attempt(DEFAULT_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, 20),
    reraise=True,
)
def http_get(url: str, params: dict = None, timeout: int = DEFAULT_TIMEOUT,
             auth: tuple = None, headers: dict = None) -> dict:
    """GET 请求并返回 JSON，失败时 tenacity 指数退避重试（仅重试网络错误和 5xx）"""
    logger.info("GET %s", url)
    http_timeout = httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)
    # 内网环境企业 HTTPS 代理会替换证书，跳过 SSL 验证避免 CERTIFICATE_VERIFY_FAILED
    verify = _get_verify(url)
    response = httpx.get(url, params=params, timeout=http_timeout, auth=auth, headers=headers, verify=verify)
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
