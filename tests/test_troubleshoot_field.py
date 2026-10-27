"""问题排查字段名解析测试：配置里的 bugid_field 被写坏时不能整表查 0 条"""
import pytest

from src.services.troubleshoot_service import _resolve_bugid_field


def test_corrupted_config_falls_back_to_real_field():
    cfg = {"bugid_field": "jira鍙?"}          # 历史配置里的乱码
    fields = {"jira号": "VCU-1", "分析结果": "失败"}
    assert _resolve_bugid_field(cfg, fields) == "jira号"


def test_configured_field_present_is_used():
    cfg = {"bugid_field": "jira号"}
    assert _resolve_bugid_field(cfg, {"jira号": "x"}) == "jira号"


def test_custom_ascii_field_kept_without_schema():
    cfg = {"bugid_field": "bug_id"}
    # 没有记录字段可参考时，纯 ASCII 的自定义字段名应当保留
    assert _resolve_bugid_field(cfg) == "bug_id"


def test_missing_config_defaults_to_jira_no():
    assert _resolve_bugid_field({}) == "jira号"
    assert _resolve_bugid_field({"bugid_field": ""}, {"jira号": "x"}) == "jira号"


def test_candidate_field_used_when_configured_absent():
    cfg = {"bugid_field": "不存在的字段"}
    assert _resolve_bugid_field(cfg, {"Jira号": "x"}) == "Jira号"
