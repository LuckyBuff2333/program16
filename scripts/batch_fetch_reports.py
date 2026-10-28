"""批量拉取 AI 分析报告并填充 Case 详情

使用方式（在内网环境运行）：
    python scripts/batch_fetch_reports.py

功能：
1. 从飞书 Bitable 获取所有 case 的飞书文档链接
2. 下载飞书文档为 Markdown 保存到本地 docs/
3. 调用 fetch_and_parse_report 解析报告并写入 case_info
4. 自动填充 decision_chain / hypothesis_table / root_cause_summary

支持参数：
    --limit N       最多处理 N 条（默认全部）
    --dry-run       只查询不执行
    --all           包括已有 decision_chain 的也重新拉取
    --skip-download 跳过文档下载（已有本地文档时用）
"""
import sys
import os
import argparse
import time
import re
from datetime import datetime

# 确保项目根目录在 sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import db
from src.config import load_config, PROJECT_ROOT
from src.services import observability_service as svc


def fetch_bitable_feishu_links() -> dict:
    """从飞书 Bitable 批量获取 jira号 → 飞书链接 的映射

    :return: {"VCU-xxx": "https://xxx.feishu.cn/docx/xxx", ...}
    """
    from src.clients import feishu_client

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    report_field = cfg.get("report_field", "AI分析结果(飞书链接)")

    if not app_token or not table_id:
        print("  [WARN] config.yaml 中未配置 feishu_bitable.app_token / table_id")
        return {}

    print(f"  正在从飞书 Bitable 获取数据... (app={app_token}, table={table_id})")
    records = feishu_client.list_bitable_records(app_token, table_id)
    print(f"  获取到 {len(records)} 条 Bitable 记录")

    link_map = {}
    for rec in records:
        fields = rec.get("fields", {})
        # 提取 jira 号
        jira_raw = fields.get(bugid_field, "")
        if isinstance(jira_raw, list):
            jira_raw = jira_raw[0] if jira_raw else ""
        elif isinstance(jira_raw, dict):
            jira_raw = jira_raw.get("text", "") or jira_raw.get("value", "")
        jira_key = str(jira_raw).strip()

        # 提取飞书链接
        link_raw = fields.get(report_field, "")
        if isinstance(link_raw, list):
            link_raw = link_raw[0] if link_raw else ""
        elif isinstance(link_raw, dict):
            link_raw = link_raw.get("text", "") or link_raw.get("link", "") or link_raw.get("value", "")
        feishu_link = str(link_raw).strip()

        if jira_key and feishu_link and feishu_link.startswith("http"):
            link_map[jira_key] = feishu_link

    print(f"  有效映射: {len(link_map)} 条 (有 jira 号 + 飞书链接)")
    return link_map


def download_feishu_doc(feishu_link: str, case_id: str) -> str:
    """下载飞书文档为 Markdown 并保存到 docs/ 目录

    :return: 本地文件路径，失败返回空字符串
    """
    from src.clients import feishu_client

    doc_id = feishu_client.extract_doc_id_from_url(feishu_link)
    if not doc_id:
        return ""

    feishu_domain = feishu_client.extract_domain_from_url(feishu_link)
    try:
        content = feishu_client.fetch_docx_as_markdown(doc_id, bugid=case_id, feishu_domain=feishu_domain)
    except Exception as e:
        print(f"    [下载失败: {e}]")
        return ""

    if not content or not content.strip():
        return ""

    # 保存到 docs/{date}/{case_id}.md
    today = datetime.now().strftime("%Y-%m-%d")
    docs_dir = os.path.join(PROJECT_ROOT, "docs", today)
    os.makedirs(docs_dir, exist_ok=True)
    local_path = os.path.join(docs_dir, f"{case_id}.md")
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)

    return local_path


def main():
    parser = argparse.ArgumentParser(description="批量拉取 AI 分析报告")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="只查询不执行")
    parser.add_argument("--all", action="store_true", help="包括已有报告的也重新拉取")
    parser.add_argument("--skip-download", action="store_true", help="跳过文档下载（已有本地文档时用）")
    args = parser.parse_args()

    # 初始化数据库
    db.init_db()
    session = db._get_session()

    try:
        # ── Step 1: 查询目标 case ──
        q = session.query(db.CaseInfo).filter(
            db.CaseInfo.is_deleted == False,
            db.CaseInfo.analysis_result == "成功",
        )
        if not args.all:
            q = q.filter(
                (db.CaseInfo.decision_chain == None)
                | (db.CaseInfo.decision_chain == "")
                | (db.CaseInfo.decision_chain == "[]")
                | (db.CaseInfo.decision_chain == "{}")
            )

        rows = q.order_by(db.CaseInfo.finish_time.desc()).all()
        total = len(rows)
        if args.limit > 0:
            rows = rows[:args.limit]

        print(f"\n{'='*60}")
        print(f"  找到 {total} 条待处理 case，本次处理 {len(rows)} 条")
        print(f"{'='*60}\n")

        if args.dry_run:
            for i, r in enumerate(rows[:20]):
                has = "有" if r.decision_chain and r.decision_chain not in ("", "[]", "{}") else "无"
                print(f"  [{i+1}] {r.case_id}  finish={r.finish_time}  DC={has}")
            if total > 20:
                print(f"  ... 还有 {total - 20} 条未显示")
            print(f"\n[dry-run] 不执行，退出")
            return

        # ── Step 2: 获取飞书链接映射 ──
        print("── Step 1/3: 获取飞书链接 ──")
        link_map = {} if args.skip_download else fetch_bitable_feishu_links()
        print()

        # ── Step 3: 下载 + 解析 ──
        print("── Step 2/3: 下载文档并解析 ──")
        success_count = 0
        fail_count = 0
        skip_count = 0

        for i, row in enumerate(rows):
            case_id = row.case_id
            print(f"[{i+1}/{len(rows)}] {case_id} ...", end=" ", flush=True)

            # 3a. 检查本地是否已有文档
            from src.core import doc_generator
            local_exists = False
            try:
                doc_generator.find_latest_document(case_id)
                local_exists = True
            except (FileNotFoundError, Exception):
                pass

            # 3b. 下载飞书文档（如果需要）
            if not local_exists and not args.skip_download:
                feishu_link = link_map.get(case_id, "")
                if feishu_link:
                    local_path = download_feishu_doc(feishu_link, case_id)
                    if local_path:
                        print(f"[下载OK] ", end="", flush=True)
                    else:
                        print(f"[下载空] ", end="", flush=True)
                else:
                    print(f"[无链接] ", end="", flush=True)

            # 3c. 调用 fetch_and_parse_report
            try:
                result = svc.fetch_and_parse_report(case_id)
                source = result.get("source", "unknown")
                print(f"OK (来源: {source})")
                success_count += 1
            except ValueError as e:
                err = str(e)[:80]
                print(f"SKIP ({err})")
                skip_count += 1
            except Exception as e:
                print(f"FAIL ({str(e)[:80]})")
                fail_count += 1

            # 限流保护
            time.sleep(0.3)

        # ── 汇总 ──
        print(f"\n{'='*60}")
        print(f"  完成！成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")
        print(f"{'='*60}\n")

    finally:
        session.close()


if __name__ == "__main__":
    main()
