r"""历史 Case 数据导入脚本（旁路脚本，不修改任何 src/ 代码）

数据源：
  - docs/*/*_daily_report.csv   — 主要数据源（7 列，含耗时）
  - docs/*/*_daily.csv          — 补充数据源（6 列，置信度/rootcause）
  - docs/study/VCU-536589_*/03_adjudication_result.json — 深度分析特例

写入目标：
  - test.db → case_info 表（INSERT OR IGNORE，幂等可重复执行）

运行方式：
  cd d:\工作\program16-master
  .\venv\Scripts\python.exe scripts\import_history_cases.py

依赖：pandas, sqlalchemy（项目已安装）
"""
import csv
import json
import os
import sys
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
DB_PATH = os.path.join(PROJECT_ROOT, "test.db")

BATCH_SIZE = 100


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════


def seconds_to_duration(val) -> str:
    """将秒数（如 1033.9, 797.6s）转换为可读格式（如 17m14s）"""
    if not val or str(val).strip() in ("", "-", "None"):
        return ""
    try:
        s = str(val).replace("s", "").strip()
        sec = float(s)
        if sec <= 0:
            return ""
        m, r = divmod(int(sec), 60)
        return f"{m}m{r}s" if m > 0 else f"{r}s"
    except (ValueError, TypeError):
        return ""


def safe_float(val, default=None):
    """安全转 float，失败返回 default"""
    if val is None or str(val).strip() in ("", "-", "None", "失败"):
        return default
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


def clean_jira_no(val: str) -> str:
    """清洗 jira 号：去除首尾空白、BOM 标记"""
    if not val:
        return ""
    return val.strip().lstrip("\ufeff").strip()


# ══════════════════════════════════════════════════════════════
# 数据读取
# ══════════════════════════════════════════════════════════════


def read_daily_reports() -> dict:
    """遍历 docs/ 下所有 *_daily_report.csv，按 jira号 合并（后日期覆盖前日期）

    :return: {jira号: {执行结果, 触发时间, 执行时间, 分析耗时, 分析结果, 备注}}
    """
    data = {}
    count = 0
    for day_dir in sorted(os.listdir(DOCS_DIR)):
        day_path = os.path.join(DOCS_DIR, day_dir)
        if not os.path.isdir(day_path):
            continue
        for fname in os.listdir(day_path):
            if not fname.endswith("_daily_report.csv"):
                continue
            fpath = os.path.join(day_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        jira = clean_jira_no(row.get("jira号", ""))
                        if not jira:
                            continue
                        data[jira] = {
                            "exec_result": row.get("执行结果", "").strip(),
                            "trigger_time": row.get("触发时间", "").strip(),
                            "exec_time": row.get("执行时间", "").strip(),
                            "duration_sec": row.get("分析耗时", "").strip(),
                            "analysis_result": row.get("分析结果", "").strip(),
                            "remark": row.get("备注", "").strip(),
                        }
                        count += 1
            except Exception as e:
                print(f"  [WARN] 读取失败 {fpath}: {e}")
    print(f"  daily_report.csv: 读取 {count} 行, 去重后 {len(data)} 条")
    return data


def read_daily_csv_supplement() -> dict:
    """遍历 docs/ 下所有 *_daily.csv，提取有值的 rootcause 和置信度

    :return: {jira号: {rootcause, confidence, trigger_time}}
    """
    data = {}
    count = 0
    for day_dir in sorted(os.listdir(DOCS_DIR)):
        day_path = os.path.join(DOCS_DIR, day_dir)
        if not os.path.isdir(day_path):
            continue
        for fname in os.listdir(day_path):
            if not fname.endswith("_daily.csv"):
                continue
            # 排除 daily_report.csv
            if "_daily_report" in fname:
                continue
            fpath = os.path.join(day_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        jira = clean_jira_no(row.get("jira号", ""))
                        if not jira:
                            continue
                        rootcause = (row.get("rootcause") or "").strip()
                        conf = (row.get("结果置信度") or "").strip()
                        trigger_time = (row.get("分析问题时间") or "").strip()
                        # 只收集有实质数据的行
                        if rootcause or (conf and conf not in ("", "-", "None", "0")):
                            data[jira] = {
                                "rootcause": rootcause,
                                "confidence": conf,
                                "trigger_time": trigger_time,
                            }
                            count += 1
            except Exception as e:
                print(f"  [WARN] 读取失败 {fpath}: {e}")
    print(f"  daily.csv 补充: 有实质数据 {count} 行, 去重后 {len(data)} 条")
    return data


# ══════════════════════════════════════════════════════════════
# VCU-536589 深度分析数据转换
# ══════════════════════════════════════════════════════════════


def load_vcu536589_study() -> dict:
    """读取 VCU-536589 的 adjudication_result.json 并转换为 case_info 格式

    :return: {"decision_chain": [...], "hypothesis_table": [...],
              "root_cause_summary": str, "conf": float, "converged": bool,
              "problem_desc": str}
    """
    study_dir = os.path.join(DOCS_DIR, "study", "VCU-536589_5dac96f2", "VCU-536589_5dac96f2")
    json_path = os.path.join(study_dir, "03_adjudication_result.json")
    if not os.path.exists(json_path):
        print("  [WARN] VCU-536589 study JSON 不存在，跳过深度转换")
        return {}

    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # ── 1. 转换 hypothesis_table ──
    # conclusions[] → hypothesis_table[]
    hypothesis_table = []
    for i, c in enumerate(raw.get("conclusions", [])):
        hypothesis_table.append({
            "key": str(i + 1),
            "hypothesis": c.get("statement", ""),
            "verdict": "confirmed" if c.get("category") == "confirmed" else "rejected",
            "evidence": ", ".join(c.get("line_refs", [])),
            "remark": f"{c.get('severity', '')} / conf {c.get('confidence', '')}",
        })

    # ── 2. 转换 decision_chain ──
    # timeline[] → 单 round 的 stages，按事件分组
    timeline = raw.get("timeline", [])
    events = []
    for t in timeline:
        events.append({
            "time": t.get("time", ""),
            "text": f"{t.get('event', '')} — {t.get('detail', '')}",
        })

    # e2e_timing[] → 作为阶段信息
    e2e = raw.get("e2e_timing", [])
    stages = []
    if e2e:
        for chain in e2e:
            stages.append({
                "stage": chain.get("chain", ""),
                "duration": chain.get("latency", ""),
                "events": [
                    {"time": chain.get("start_time", ""), "text": f"起点: {chain.get('start_node', '')}"},
                    {"time": chain.get("end_time", ""), "text": f"终点: {chain.get('end_node', '')}"},
                ],
            })
    else:
        # 兜底：把所有 timeline 事件归为一个阶段
        stages.append({
            "stage": "完整分析时间线",
            "duration": "",
            "events": events,
        })

    decision_chain = [{"round": 1, "stages": stages}]

    # ── 3. 提取根因和置信度 ──
    causal_chain = raw.get("causal_chain", "")
    core_conflict = raw.get("core_conflict", "")
    root_cause = causal_chain if causal_chain else core_conflict

    overall_conf = raw.get("overall_confidence", "medium")
    conf_map = {"high": 0.85, "medium": 0.65, "low": 0.40}
    conf = conf_map.get(overall_conf, 0.50)

    # ── 4. 问题描述 ──
    problem_desc = core_conflict

    result = {
        "decision_chain": decision_chain,
        "hypothesis_table": hypothesis_table,
        "root_cause_summary": root_cause,
        "conf": conf,
        "converged": overall_conf == "high",
        "problem_desc": problem_desc,
    }
    print(f"  VCU-536589 深度转换完成: {len(hypothesis_table)} 条假设, "
          f"{len(stages)} 个阶段, conf={conf}")
    return result


# ══════════════════════════════════════════════════════════════
# 数据合并与写入
# ══════════════════════════════════════════════════════════════


def build_records(reports: dict, supplements: dict, study: dict) -> list:
    """合并两个数据源，生成 case_info 记录列表

    :return: [(case_id, vcu_number, finish_time, duration, conf, converged,
               case_status, backflow_status, problem_desc, root_cause_summary,
               decision_chain_json, hypothesis_table_json, created_at, updated_at, is_deleted), ...]
    """
    # 以 daily_report 为主键集合
    all_jiras = set(reports.keys())
    # 补充源中独有的 jira 也加入
    for jira in supplements:
        all_jiras.add(jira)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    default_root_cause = "历史数据暂无根因，可点击一键复测生成"
    records = []

    for jira in sorted(all_jiras):
        rpt = reports.get(jira, {})
        sup = supplements.get(jira, {})

        # ── 字段映射 ──
        case_id = jira
        vcu_number = jira

        # finish_time: 优先执行时间，回退触发时间，再回退 daily.csv 的分析问题时间
        finish_time = (rpt.get("exec_time")
                       or rpt.get("trigger_time")
                       or sup.get("trigger_time")
                       or "")

        # duration: 从秒数转换
        duration = seconds_to_duration(rpt.get("duration_sec"))

        # conf: 优先 daily.csv 的置信度，回退 None
        conf = safe_float(sup.get("confidence"))

        # case_status: 从执行结果映射
        exec_result = rpt.get("exec_result", "")
        analysis_result = rpt.get("analysis_result", "")
        if exec_result == "成功":
            case_status = "已分析"
        elif exec_result == "失败":
            case_status = "分析失败"
        elif analysis_result:
            case_status = "已分析" if analysis_result == "成功" else "分析失败"
        else:
            case_status = "历史导入"

        # backflow_status: 默认为空
        backflow_status = ""

        # root_cause: 优先 daily.csv，回退默认值
        root_cause = sup.get("rootcause") or default_root_cause

        # problem_desc: 默认为空
        problem_desc = ""

        # converged
        converged = False

        # JSON 大字段
        decision_chain_json = "[]"
        hypothesis_table_json = "[]"

        # ── VCU-536589 特例：覆盖深度分析数据 ──
        if jira == "VCU-536589" and study:
            decision_chain_json = json.dumps(study["decision_chain"], ensure_ascii=False)
            hypothesis_table_json = json.dumps(study["hypothesis_table"], ensure_ascii=False)
            root_cause = study["root_cause_summary"]
            conf = study["conf"]
            converged = study["converged"]
            problem_desc = study["problem_desc"]
            case_status = "深度分析"

        records.append((
            case_id, vcu_number, finish_time, duration,
            conf, converged, case_status, backflow_status,
            problem_desc, root_cause,
            decision_chain_json, hypothesis_table_json,
            now, now, False,
        ))

    return records


def batch_insert(records: list, dry_run: bool = False) -> dict:
    """批量插入到 case_info 表（INSERT OR IGNORE 防重）

    :return: {"total": int, "inserted": int, "skipped": int}
    """
    if dry_run:
        print(f"\n  [DRY-RUN] 共 {len(records)} 条记录待写入（未实际执行）")
        # 预览前 5 条
        for i, r in enumerate(records[:5]):
            print(f"    [{i+1}] {r[0]:20s} | {r[2]:20s} | {r[3]:10s} | {r[6]:10s}")
        if len(records) > 5:
            print(f"    ... 还有 {len(records) - 5} 条")
        return {"total": len(records), "inserted": 0, "skipped": 0}

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 先查询已有的 case_id 集合
    cur.execute("SELECT case_id FROM case_info WHERE is_deleted = 0")
    existing = {row[0] for row in cur.fetchall()}

    # 过滤已存在的
    to_insert = [r for r in records if r[0] not in existing]
    skipped = len(records) - len(to_insert)

    if not to_insert:
        conn.close()
        print(f"\n  全部 {len(records)} 条已存在，无需插入")
        return {"total": len(records), "inserted": 0, "skipped": skipped}

    # 批量插入
    sql = """INSERT OR IGNORE INTO case_info
             (case_id, vcu_number, finish_time, duration,
              conf, converged, case_status, backflow_status,
              problem_desc, root_cause_summary,
              decision_chain, hypothesis_table,
              created_at, updated_at, is_deleted)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    inserted = 0
    for i in range(0, len(to_insert), BATCH_SIZE):
        batch = to_insert[i:i + BATCH_SIZE]
        cur.executemany(sql, batch)
        inserted += cur.rowcount
        conn.commit()
        print(f"    批次 {i // BATCH_SIZE + 1}: 提交 {len(batch)} 条, 实际插入 {cur.rowcount} 条")

    conn.close()
    print(f"\n  写入完成: 总计 {len(records)} 条, 插入 {inserted} 条, 跳过 {skipped} 条(已存在)")
    return {"total": len(records), "inserted": inserted, "skipped": skipped}


def update_vcu536589_study(study: dict, dry_run: bool = False):
    """单独更新 VCU-536589 的深度分析字段（如果该记录已存在）"""
    if not study or dry_run:
        return

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 检查是否已存在
    cur.execute("SELECT case_id FROM case_info WHERE case_id = 'VCU-536589' AND is_deleted = 0")
    if not cur.fetchone():
        conn.close()
        return

    dc_json = json.dumps(study["decision_chain"], ensure_ascii=False)
    ht_json = json.dumps(study["hypothesis_table"], ensure_ascii=False)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""UPDATE case_info SET
                   decision_chain = ?,
                   hypothesis_table = ?,
                   root_cause_summary = ?,
                   conf = ?,
                   converged = ?,
                   problem_desc = ?,
                   case_status = '深度分析',
                   updated_at = ?
                   WHERE case_id = 'VCU-536589'""",
                (dc_json, ht_json, study["root_cause_summary"],
                 study["conf"], study["converged"], study["problem_desc"], now))
    conn.commit()
    conn.close()
    print(f"  VCU-536589 深度分析数据已更新")


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=" * 60)
        print("  DRY-RUN 模式：只读取和预览，不写入数据库")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  历史 Case 数据导入")
        print("=" * 60)

    print(f"\n项目根目录: {PROJECT_ROOT}")
    print(f"数据库路径: {DB_PATH}")
    print(f"docs 目录:  {DOCS_DIR}")

    # 1. 读取数据源
    print("\n[1/4] 读取 daily_report.csv ...")
    reports = read_daily_reports()

    print("\n[2/4] 读取 daily.csv 补充数据 ...")
    supplements = read_daily_csv_supplement()

    print("\n[3/4] 读取 VCU-536589 深度分析数据 ...")
    study = load_vcu536589_study()

    # 2. 合并生成记录
    print("\n[4/4] 合并数据并写入 case_info ...")
    records = build_records(reports, supplements, study)
    print(f"  合并后共 {len(records)} 条唯一记录")

    # 3. 如果 VCU-536589 不在 CSV 数据中，单独追加
    vcu_ids = {r[0] for r in records}
    if "VCU-536589" not in vcu_ids and study:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dc_json = json.dumps(study["decision_chain"], ensure_ascii=False)
        ht_json = json.dumps(study["hypothesis_table"], ensure_ascii=False)
        records.append((
            "VCU-536589", "VCU-536589", "", "",
            study["conf"], study["converged"], "深度分析", "",
            study["problem_desc"], study["root_cause_summary"],
            dc_json, ht_json,
            now, now, False,
        ))
        print("  VCU-536589 不在 CSV 中，已从 study 数据单独追加")

    # 4. 批量写入
    result = batch_insert(records, dry_run=dry_run)

    # 5. 更新 VCU-536589 深度数据（如果已存在于 DB 但需要覆盖）
    if not dry_run and study:
        update_vcu536589_study(study)

    # 5. 汇总
    print("\n" + "=" * 60)
    print(f"  导入完成" if not dry_run else "  预览完成（未写入）")
    print(f"  总计: {result['total']} 条")
    print(f"  插入: {result['inserted']} 条")
    print(f"  跳过: {result['skipped']} 条")
    if not dry_run:
        print(f"\n  回滚命令: DELETE FROM case_info WHERE root_cause_summary LIKE '历史数据暂无%'")
    print("=" * 60)


if __name__ == "__main__":
    main()
