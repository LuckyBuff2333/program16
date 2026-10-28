r"""飞书多维表格数据拉取测试脚本（独立运行，不修改任何现有代码）

功能：
  1. 获取 tenant_access_token（复用 feishu_client 的缓存机制）
  2. 全量拉取指定多维表格的记录（自动翻页）
  3. 清洗飞书返回的复杂嵌套字段（多行文本、人员、附件等）为扁平字符串
  4. 打印清洗后的数据，方便查看真实结构

使用方式：
  1. 先在 config/config.yaml 中添加 feishu_bitable 配置（见下方说明）
  2. 运行：
     cd d:\工作\program16-master
     .\venv\Scripts\python.exe scripts\fetch_bitable_test.py

config.yaml 中需要添加的配置：
  feishu_bitable:
    app_id: "cli_xxxxx"
    app_secret: "xxxxx"
    app_token: "xxxxx"          # 多维表格 URL 中 /base/ 后的字符串
    table_id: "tblxxxxx"       # "数据沉淀" 那张表的 ID
"""
import json
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ==================================================================
# 字段清洗：将飞书复杂嵌套结构扁平化
# ==================================================================


def _clean_field_value(val):
    """清洗单个字段值，将飞书复杂格式转为扁平字符串

    飞书多维表格字段类型及返回格式：
    - 多行文本: [{"type": "text", "text": "xxx"}, ...]
    - 单选: "选项值"
    - 多选: ["选项1", "选项2"]
    - 人员: [{"id": "xxx", "name": "张三", "en_name": "Zhang San"}, ...]
    - 日期: 1704067200000 (毫秒时间戳)
    - 附件: [{"name": "file.pdf", "token": "xxx", ...}, ...]
    - 复选框: true/false
    - 数字: 123.45
    """
    if val is None:
        return ""

    # 列表类型（多行文本 / 人员 / 附件 / 多选）
    if isinstance(val, list):
        if not val:
            return ""
        first = val[0]

        # 多行文本: [{"type": "text", "text": "xxx"}, ...]
        if isinstance(first, dict) and "text" in first:
            return "".join(seg.get("text", "") for seg in val)

        # 人员: [{"id": "xxx", "name": "张三"}, ...]
        if isinstance(first, dict) and "name" in first:
            return ", ".join(p.get("name", p.get("en_name", "")) for p in val)

        # 附件: [{"name": "file.pdf", "token": "xxx"}, ...]
        if isinstance(first, dict) and "token" in first:
            return ", ".join(f.get("name", f.get("token", "")) for f in val)

        # 关联: [{"record_ids": [...], "table_id": "xxx"}]
        if isinstance(first, dict) and "record_ids" in first:
            all_ids = []
            for item in val:
                all_ids.extend(item.get("record_ids", []))
            return ", ".join(all_ids)

        # 多选: ["选项1", "选项2"]
        if isinstance(first, str):
            return ", ".join(val)

        # 其他列表: JSON 序列化
        return json.dumps(val, ensure_ascii=False)

    # 数字类型（日期是毫秒时间戳）
    if isinstance(val, (int, float)):
        if val > 1000000000000:
            try:
                return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass
        return val

    # 字典类型
    if isinstance(val, dict):
        if "value" in val:
            return val["value"]
        if "text" in val and "link" in val:
            return f"{val['text']} ({val['link']})"
        return json.dumps(val, ensure_ascii=False)

    return val


def clean_record(record):
    """清洗一条飞书记录，返回扁平化的 fields 字典"""
    raw_fields = record.get("fields", {})
    cleaned = {"record_id": record.get("record_id", "")}
    for key, val in raw_fields.items():
        cleaned[key] = _clean_field_value(val)
    return cleaned


# ==================================================================
# 主流程
# ==================================================================


def _parse_wiki_url(url_or_token):
    """从飞书 URL 中提取 wiki token 或 bitable app_token

    支持的 URL 格式：
    - Wiki: https://xxx.feishu.cn/wiki/VSWFwwkLTiZC6QkeZY4csbwUnjd
    - Bitable: https://xxx.feishu.cn/base/XxxXxx?table=tblXxx
    - 纯 token: VSWFwwkLTiZC6QkeZY4csbwUnjd
    """
    if not url_or_token:
        return None, None, None
    # Wiki URL
    if "/wiki/" in url_or_token:
        token = url_or_token.split("/wiki/")[-1].split("?")[0].split("#")[0]
        return "wiki", token, None
    # Bitable URL
    if "/base/" in url_or_token:
        token = url_or_token.split("/base/")[-1].split("?")[0].split("#")[0]
        # 尝试提取 table_id
        table_id = None
        if "table=" in url_or_token:
            table_id = url_or_token.split("table=")[-1].split("&")[0]
        return "bitable", token, table_id
    # 纯 token
    return "token", url_or_token, None


def main():
    from src.config import load_config
    from src.clients import feishu_client

    cfg = load_config()
    bitable_cfg = cfg.get("feishu_bitable", {})

    app_id = bitable_cfg.get("app_id", "")
    app_secret = bitable_cfg.get("app_secret", "")
    app_token = bitable_cfg.get("app_token", "")
    table_id = bitable_cfg.get("table_id", "")
    wiki_url = bitable_cfg.get("wiki_url", "")

    if not app_id or not app_secret:
        print("=" * 60)
        print("  配置缺失！请在 config/config.yaml 中添加：")
        print()
        print("feishu_bitable:")
        print('  app_id: "cli_xxxxx"')
        print('  app_secret: "xxxxx"')
        print('  wiki_url: "https://xxx.feishu.cn/wiki/xxxxx"  # 飞书表链接')
        print("  # 或者直接用 app_token + table_id：")
        print('  # app_token: "xxxxx"')
        print('  # table_id: "tblxxxxx"')
        print("=" * 60)
        return

    # 步骤 1：获取 Token
    print("=" * 60)
    print(f"  App ID: {app_id[:8]}...{app_id[-4:]}")
    print("=" * 60)

    try:
        token = feishu_client.get_tenant_access_token(app_id, app_secret)
        print(f"  Token 获取成功: {token[:20]}...{token[-8:]}")
    except Exception as e:
        print(f"  Token 获取失败: {e}")
        return

    # 步骤 2：解析链接，获取 app_token
    if wiki_url and not app_token:
        url_type, parsed_token, url_table_id = _parse_wiki_url(wiki_url)
        print(f"\n  Wiki URL: {wiki_url[:60]}...")
        print(f"  URL 类型: {url_type}, Token: {parsed_token}")

        if url_type == "wiki":
            try:
                app_token = feishu_client.get_wiki_node_app_token(parsed_token)
                print(f"  Wiki -> Bitable app_token: {app_token}")
            except Exception as e:
                print(f"  解析 Wiki 节点失败: {e}")
                return
        elif url_type == "bitable":
            app_token = parsed_token
            if url_table_id and not table_id:
                table_id = url_table_id
        else:
            app_token = parsed_token

    if not app_token:
        print("  缺少 app_token，请配置 wiki_url 或 app_token")
        return

    # 步骤 3：列出所有数据表
    print(f"\n  正在列出多维表格中的数据表...")
    try:
        tables = feishu_client.list_bitable_tables(app_token)
        print(f"  找到 {len(tables)} 张数据表：")
        for i, t in enumerate(tables):
            marker = " <--" if t["table_id"] == table_id else ""
            print(f"    [{i+1}] {t['name']:30s}  table_id={t['table_id']}{marker}")
    except Exception as e:
        print(f"  列出数据表失败: {e}")
        return

    # 如果没有指定 table_id，尝试自动查找“数据沉淀”表
    if not table_id and tables:
        for t in tables:
            if "数据沉淀" in t.get("name", ""):
                table_id = t["table_id"]
                print(f"\n  自动选择“数据沉淀”表: {table_id}")
                break
        if not table_id:
            table_id = tables[0]["table_id"]
            print(f"\n  未找到“数据沉淀”表，默认使用第一张: {tables[0]['name']} ({table_id})")

    print(f"\n  App Token: {app_token}")
    print(f"  Table ID:  {table_id}")
    print("=" * 60)

    # 步骤 4：拉取记录（自动翻页）
    print("\n  正在拉取记录（自动翻页）...")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        print(f"  共拉取 {len(records)} 条记录\n")
    except Exception as e:
        print(f"  拉取失败: {e}")
        return

    if not records:
        print("  表中没有记录")
        return

    # 步骤 5：打印原始字段结构
    print("=" * 60)
    print("  原始字段名列表（第一条记录）：")
    first_raw = records[0].get("fields", {})
    for i, key in enumerate(first_raw.keys()):
        val = first_raw[key]
        type_hint = type(val).__name__
        if isinstance(val, list) and val:
            type_hint = f"list[{type(val[0]).__name__}]"
        elif isinstance(val, str):
            type_hint = f"str({len(val)})"
        print(f"  [{i+1:2d}] {key:30s} ({type_hint})")

    # 步骤 6：清洗并打印前 5 条
    print("\n" + "=" * 60)
    print("  清洗后的数据（前 5 条）：")
    print("=" * 60)

    cleaned_records = [clean_record(r) for r in records]

    for i, rec in enumerate(cleaned_records[:5]):
        print(f"\n-- 记录 {i + 1} (record_id={rec['record_id']}) --")
        for key, val in rec.items():
            if key == "record_id":
                continue
            display = str(val)
            if len(display) > 120:
                display = display[:120] + "..."
            print(f"  {key:30s}: {display}")

    # 步骤 7：导出完整数据到 JSON
    output_path = os.path.join(PROJECT_ROOT, "data", "bitable_export.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_records, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  完整数据已导出: {output_path} ({len(cleaned_records)} 条)")

    # 字段覆盖率统计
    print("\n" + "=" * 60)
    print("  字段覆盖率统计：")
    all_keys = set()
    for rec in cleaned_records:
        all_keys.update(rec.keys())
    all_keys.discard("record_id")

    total = len(cleaned_records)
    for key in sorted(all_keys):
        non_empty = sum(1 for rec in cleaned_records if rec.get(key))
        pct = non_empty / total * 100 if total else 0
        bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
        print(f"  {key:30s} [{bar}] {non_empty:4d}/{total} ({pct:.0f}%)")


if __name__ == "__main__":
    main()
