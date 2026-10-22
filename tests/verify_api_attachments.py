"""验证 VCU-559847 的 API 附件名，结果写入文件"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

result_file = os.path.join(os.path.dirname(__file__), "api_verify.txt")
lines = []

from src.clients import jira_client as jc

issue = jc.fetch_issue('VCU-559847')
attachments = (issue.get("fields") or {}).get("attachment") or []

lines.append(f"VCU-559847 attachments ({len(attachments)}):")
for att in attachments:
    lines.append(f"  id={att.get('id','')} | filename={att.get('filename','')} | created={att.get('created','')}")

# 也查下前后两个 jira 号，看有没有串
for neighbor in ['VCU-559846', 'VCU-559848']:
    try:
        ni = jc.fetch_issue(neighbor)
        na = (ni.get("fields") or {}).get("attachment") or []
        lines.append(f"\n{neighbor} attachments ({len(na)}):")
        for att in na:
            lines.append(f"  id={att.get('id','')} | filename={att.get('filename','')} | created={att.get('created','')}")
    except Exception as e:
        lines.append(f"\n{neighbor}: ERROR - {e}")

with open(result_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print("done")
