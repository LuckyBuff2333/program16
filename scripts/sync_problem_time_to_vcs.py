"""同步数据沉淀的「分析问题时间」到 VCS BUG 表的「问题发生时间」

规则：
1. 从 VCS BUG 表拉取全部 Jira 号
2. 从数据沉淀表查同一 Jira 号、分析结果=成功 的记录
3. 同 Jira 号有多条成功记录时取「分析开始时间」最新的一条
4. 将该条的「分析问题时间」写入 VCS BUG 表的「问题发生时间」
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.clients import feishu_client

APP_TOKEN = "HOARbsrB0aSViFs5AjNchSQ0nAf"
VCS_TABLE = "tblr4oboVbKsV6y1"
DATA_TABLE = "tblM5keGYh2y0aSX"


def _text(val):
    """提取飞书字段文本值"""
    if isinstance(val, list):
        return " ".join(str(v.get("text", v)) if isinstance(v, dict) else str(v) for v in val)
    if isinstance(val, dict):
        return val.get("text", str(val))
    return str(val) if val else ""


def main():
    # 1. 拉取 VCS BUG 表全部记录
    print("拉取 VCS BUG 表...")
    vcs_recs = feishu_client.list_bitable_records(APP_TOKEN, VCS_TABLE)
    print(f"  VCS BUG 共 {len(vcs_recs)} 条")

    # 收集 Jira 号集合
    vcs_map = {}  # jira_no -> record_id
    for rec in vcs_recs:
        fields = rec.get("fields", {})
        jira_no = _text(fields.get("jira号", "")).strip().upper()
        if not jira_no:
            jira_no = _text(fields.get("Jira链接", "")).strip().upper()
        if jira_no:
            vcs_map[jira_no] = rec.get("record_id", "")
    print(f"  有效 Jira 号: {len(vcs_map)} 个")

    # 2. 拉取数据沉淀表全部记录
    print("拉取数据沉淀表...")
    data_recs = feishu_client.list_bitable_records(APP_TOKEN, DATA_TABLE)
    print(f"  数据沉淀共 {len(data_recs)} 条")

    # 按 Jira 号分组，筛选分析结果=成功 且 触发来源=线上，取分析开始时间最新的一条
    best_time = {}  # jira_no -> (分析开始时间, 分析问题时间)
    for rec in data_recs:
        fields = rec.get("fields", {})
        jira_no = _text(fields.get("jira号", "")).strip().upper()
        if not jira_no:
            continue
        result = _text(fields.get("分析结果", "")).strip()
        if result != "成功":
            continue
        source = _text(fields.get("触发来源", "")).strip()
        if source != "parseFullTicket":
            continue
        start_time = _text(fields.get("分析开始时间", "")).strip()
        problem_time = _text(fields.get("分析问题时间", "")).strip()
        if not problem_time:
            continue
        prev = best_time.get(jira_no)
        if prev is None or start_time > prev[0]:
            best_time[jira_no] = (start_time, problem_time)

    print(f"  有成功分析且带问题时间的 Jira: {len(best_time)} 个")

    # 3. 构建更新列表
    updates = []
    skipped = 0
    for jira_no, vcs_rid in vcs_map.items():
        if jira_no not in best_time:
            continue
        _, problem_time = best_time[jira_no]
        updates.append({
            "record_id": vcs_rid,
            "fields": {"问题发生时间": problem_time}
        })
    skipped = len(vcs_map) - len(updates)
    print(f"\n待更新: {len(updates)} 条, 无匹配跳过: {skipped} 条")

    if not updates:
        print("无需更新，退出")
        return

    # 4. 分批写入（每批 100 条）
    print(f"开始写入 VCS BUG 表...")
    total = len(updates)
    for i in range(0, total, 100):
        batch = updates[i:i + 100]
        feishu_client.update_bitable_records(APP_TOKEN, VCS_TABLE, batch)
        print(f"  已写入 {min(i + 100, total)}/{total}")

    print(f"\n完成！共更新 {total} 条「问题发生时间」")


if __name__ == "__main__":
    main()
