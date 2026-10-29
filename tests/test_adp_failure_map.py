"""ADP 失败归因与错误码分级单测"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.adp_ops import (
    classify_adp_failure, CAPACITY_LIMIT_CODES, RATE_LIMIT_CODES,
    RETRYABLE_ERROR_CODES, SESSION_CONFLICT_CODES,
)


def test_no_log_attachment_reason():
    assert classify_adp_failure(error="无日志附件") == "无日志附件"
    assert classify_adp_failure(error="无附件") == "无日志附件"
    assert classify_adp_failure(error="没有日志附件（已有: a.log）") == "无日志附件"


def test_attach_api_error_reason():
    assert classify_adp_failure(error="ADP附件接口异常") == "ADP附件接口异常"


def test_enterprise_tpm_is_capacity_limit():
    # 企业级 TPM（实测日志出现 460701），应按容量限流处理（退避 300s）
    assert "460701" in CAPACITY_LIMIT_CODES
    assert classify_adp_failure(signal_info={"error_code": "460701"}) == "ADP容量限流(460701)"


def test_space_and_app_tpm():
    for code in ("460711", "460721"):
        assert classify_adp_failure(signal_info={"error_code": code}) == f"ADP容量限流({code})"


def test_concurrency_reasons():
    for code in RATE_LIMIT_CODES:
        assert classify_adp_failure(signal_info={"error_code": code}) == f"ADP并发限流({code})"
    for code in RETRYABLE_ERROR_CODES:
        assert classify_adp_failure(signal_info={"error_code": code}) == f"ADP模型超时({code})"
    for code in SESSION_CONFLICT_CODES:
        assert classify_adp_failure(signal_info={"error_code": code}) == f"ADP会话冲突({code})"
