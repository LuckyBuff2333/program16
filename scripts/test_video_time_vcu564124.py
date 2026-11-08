# -*- coding: utf-8 -*-
"""测试 VCU-564124 视频时间提取，期望提取到 14:52"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import setup_logger
logger = setup_logger("test_video")

from src.clients import jira_client as _jc
from src.services.server_legacy import _diag_extract_time_from_video_simple, _has_gmlogger_logs

BUGID = "VCU-564124"

def main():
    print(f"=== 测试 {BUGID} 视频时间提取 ===")
    # 1. 获取 issue
    print(f"[1] 获取 {BUGID} 信息...")
    issue = _jc.fetch_issue(BUGID)
    fields = issue.get("fields") or {}
    attachments = fields.get("attachment") or []
    print(f"    附件数: {len(attachments)}")
    
    # 2. 检查 gmlogger
    has_log = _has_gmlogger_logs(attachments, BUGID)
    print(f"    有日志附件: {has_log}")
    
    # 列出视频附件
    video_atts = [a for a in attachments if (a.get("mimeType") or "").startswith("video")]
    print(f"    视频附件数: {len(video_atts)}")
    for v in video_atts:
        print(f"      - {v.get('filename')} ({v.get('size', 0) / 1024 / 1024:.1f}MB)")
    
    if not has_log:
        print(f"    ⚠ 无日志附件，按新逻辑会跳过提取")
        return
    
    # 3. 执行视频时间提取
    print(f"\n[2] 开始视频时间提取...")
    result = _diag_extract_time_from_video_simple(issue)
    print(f"\n=== 提取结果: {result or '(空)'} ===")
    
    if result:
        if "14:52" in result:
            print("✓ 成功提取到 14:52！")
        else:
            print(f"✗ 提取到 {result}，但期望 14:52")
    else:
        print("✗ 未提取到任何时间")

if __name__ == "__main__":
    main()
