"""第二轮补充：VCS BUG 表中「问题发生时间」为空的记录，从云端触发时间缓存补填

规则：
1. 从 VCS BUG 表拉取全部记录，筛选「问题发生时间」为空的
2. 拿这些 Jira 号去云端触发时间缓存查
3. 命中且有触发时间的，写入 VCS BUG 的「问题发生时间」
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client
from src.services.trigger_ops import _load_cloud_trigger_cache

APP_TOKEN = "HOARbsrB0aSViFs5AjNchSQ0nAf"
VCS_TABLE = "tblr4oboVbKsV6y1"


def _text(val):
    """提取飞书字段文本值"""
    if isinstance(val, list):
        return " ".join(str(v.get("text", v)) if isinstance(v, dict) else str(v) for v in val)
    if isinstance(val, dict):
        return val.get("text", str(val))
    return str(val) if val else ""


def main():
    # 1. 拉取 VCS BUG 表
    print("拉取 VCS BUG 表...")
    vcs_recs = feishu_client.list_bitable_records(APP_TOKEN, VCS_TABLE)
    print(f"  共 {len(vcs_recs)} 条")

    # 筛选「问题发生时间」为空的记录
    empty_time = []  # [(record_id, jira_no)]
    for rec in vcs_recs:
        fields = rec.get("fields", {})
        pt = _text(fields.get("问题发生时间", "")).strip()
        if pt:
            continue
        jira_no = _text(fields.get("jira号", "")).strip().upper()
        if not jira_no:
            jira_no = _text(fields.get("Jira链接", "")).strip().upper()
        if jira_no:
            empty_time.append((rec.get("record_id", ""), jira_no))

    print(f"  问题发生时间为空: {len(empty_time)} 条")

    if not empty_time:
        print("无需补充，退出")
        return

    # 2. 加载云端触发时间缓存
    print("加载云端触发时间缓存...")
    cloud_times, cloud_keys = _load_cloud_trigger_cache()
    print(f"  有触发时间: {len(cloud_times)} 个, 已记录(含空标记): {len(cloud_keys)} 个")

    # 3. 匹配
    updates = []
    for rid, jira_no in empty_time:
        tt = cloud_times.get(jira_no, "").strip()
        if tt:
            updates.append({
                "record_id": rid,
                "fields": {"问题发生时间": tt}
            })

    hit_rate = len(updates) / len(empty_time) * 100 if empty_time else 0
    print(f"\n云端命中: {len(updates)} 条 ({hit_rate:.1f}%), 未命中: {len(empty_time) - len(updates)} 条")

    if not updates:
        print("无需写入，退出")
        return

    # 4. 分批写入
    print(f"开始写入 VCS BUG 表...")
    total = len(updates)
    for i in range(0, total, 100):
        batch = updates[i:i + 100]
        feishu_client.update_bitable_records(APP_TOKEN, VCS_TABLE, batch)
        print(f"  已写入 {min(i + 100, total)}/{total}")

    print(f"\n完成！从云端缓存补填了 {total} 条「问题发生时间」")


if __name__ == "__main__":
    main()
