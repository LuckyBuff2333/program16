"""ADP 过程叙述识别（续接条件）单测"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.adp_ops import _looks_like_process_narration


def test_process_narration_with_multiple_keywords():
    text = (
        "我先加载治理技能，现在进入数据层预热，"
        "让我检查 report_data 的 schema，接下来重新下载 manifest 里的分卷。"
    ) * 8
    assert _looks_like_process_narration(text) is True


def test_short_text_not_narration():
    assert _looks_like_process_narration("让我看看") is False


def test_plain_conclusion_not_narration():
    text = (
        "根因是账号门控采用事后检查制，点击后回弹。"
        "修复建议：渲染时对智慧领航档置 isDisable=true。"
    ) * 3
    # 只有“根因/修复建议”这类收尾词，没有过程叙述关键词
    assert _looks_like_process_narration(text) is False


def test_two_keywords_is_enough():
    text = ("我先把流程跑通。" * 100) + "然后重试一次。"
    assert _looks_like_process_narration(text) is True
