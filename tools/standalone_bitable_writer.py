#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书多维表格写入模拟工具 (standalone_bitable_writer.py)

功能：
  1. 列出多维表格字段及类型
  2. 模拟/实际写入单条/多条记录
  3. 自动根据字段类型格式化值（URL/文本/数字）
  4. 支持内外网环境（通过环境变量或命令行参数切换）

使用方法：
  python tools/standalone_bitable_writer.py --list-fields
  python tools/standalone_bitable_writer.py --write --bugid VCU-xxx --rootcause "xxx" --comment "xxx" --confidence 0.95 --dry-run
  python tools/standalone_bitable_writer.py --write --bugid VCU-xxx --rootcause "xxx" --comment "xxx" --confidence 0.95
"""

import argparse
import json
import sys
import os
import traceback

# 支持直接运行（未安装依赖时的回退）
try:
    import httpx
except ImportError:
    print("ERROR: 请先安装依赖: pip install httpx pyyaml")
    sys.exit(1)

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config import load_config
from src.clients import feishu_client


def _get_bitable_config():
    """获取多维表格配置"""
    cfg = load_config().get("feishu_bitable", {})
    return {
        "app_token": cfg.get("app_token", ""),
        "table_id": cfg.get("table_id", ""),
        "bugid_field": cfg.get("bugid_field", "jira号"),
    }


def list_fields():
    """列出多维表格所有字段及类型"""
    cfg = _get_bitable_config()
    app_token = cfg["app_token"]
    table_id = cfg["table_id"]
    
    print(f"\n{'='*60}")
    print(f"多维表格字段列表")
    print(f"{'='*60}")
    print(f"app_token: {app_token}")
    print(f"table_id:  {table_id}")
    print(f"{'-'*60}")
    
    try:
        fields = feishu_client.list_bitable_fields(app_token, table_id)
        TYPE_MAP = {
            1: "文本", 2: "数字", 3: "单选", 4: "多选",
            5: "日期", 7: "复选框", 11: "人员", 13: "电话",
            15: "URL", 17: "附件", 18: "关联", 20: "公式",
            21: "双向关联", 22: "地理位置", 23: "条码", 1001: "创建时间",
            1002: "创建人", 1003: "修改时间", 1004: "修改人",
        }
        for fd in fields:
            name = fd.get("field_name", "")
            ftype = fd.get("type", 0)
            type_name = TYPE_MAP.get(ftype, f"未知({ftype})")
            print(f"  [{ftype:4d}] {type_name:<10s}  {name}")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"获取字段失败: {e}")


def format_field_value(field_name: str, field_type: int, value, doc_url: str = "") -> tuple:
    """
    根据字段类型格式化值
    
    :return: (格式化后的值, 说明)
    """
    if field_type == 15:  # URL
        if doc_url:
            return {"link": doc_url, "text": str(value)[:200]}, "URL dict格式"
        else:
            return {"link": "", "text": str(value)[:200]}, "URL dict格式(无链接)"
    elif field_type == 2:  # 数字
        try:
            return float(value), "float"
        except (ValueError, TypeError):
            return 0, "float(回退)"
    else:  # 文本或其他
        return str(value)[:500], "文本字符串"


def write_record(bugid: str, rootcause: str, comment: str, confidence: float, 
                 doc_url: str = "", dry_run: bool = False):
    """写入单条记录到多维表格"""
    cfg = _get_bitable_config()
    app_token = cfg["app_token"]
    table_id = cfg["table_id"]
    bugid_field = cfg["bugid_field"]
    
    print(f"\n{'='*60}")
    print(f"写入多维表格 - {'[模拟模式]' if dry_run else '[实际写入]'}")
    print(f"{'='*60}")
    
    # 1. 获取字段列表
    try:
        fields = feishu_client.list_bitable_fields(app_token, table_id)
    except Exception as e:
        print(f"获取字段失败: {e}")
        return False
    
    field_name_map = {f.get("field_name", ""): f.get("field_name", "") for f in fields}
    field_type_map = {f.get("field_name", ""): f.get("type", 0) for f in fields}
    
    # 2. 匹配字段
    rc_field = field_name_map.get("rootcause") or field_name_map.get("Rootcause") or ""
    cs_field = field_name_map.get("AI评论总结") or field_name_map.get("评论总结") or ""
    cf_field = field_name_map.get("结果置信度") or field_name_map.get("置信度") or ""
    
    print(f"匹配字段: rootcause={rc_field!r}, AI评论总结={cs_field!r}, 结果置信度={cf_field!r}")
    
    # 3. 获取记录
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
    except Exception as e:
        print(f"获取记录失败: {e}")
        return False
    
    bugid_to_record = {}
    for rec in records:
        fields_data = rec.get("fields", {})
        field_value = fields_data.get(bugid_field, "")
        if isinstance(field_value, list):
            field_value = "".join(str(v) for v in field_value)
        field_value = str(field_value).strip()
        if field_value:
            bugid_to_record[field_value] = rec.get("record_id", "")
    
    record_id = bugid_to_record.get(bugid)
    if not record_id:
        print(f"ERROR: 未找到 bugid={bugid} 对应的记录")
        print(f"  可用 bugid 列表(前10条): {list(bugid_to_record.keys())[:10]}")
        return False
    
    print(f"找到记录: bugid={bugid} -> record_id={record_id}")
    
    # 4. 构建写入值
    fields_to_write = {}
    
    if rc_field:
        rc_type = field_type_map.get(rc_field, 0)
        rc_val, rc_desc = format_field_value(rc_field, rc_type, rootcause)
        fields_to_write[rc_field] = rc_val
        print(f"  [{rc_field}] (type={rc_type}) -> {rc_desc}: {rc_val!r}")
    
    if cs_field:
        cs_type = field_type_map.get(cs_field, 0)
        cs_val, cs_desc = format_field_value(cs_field, cs_type, comment, doc_url)
        fields_to_write[cs_field] = cs_val
        print(f"  [{cs_field}] (type={cs_type}) -> {cs_desc}: {cs_val!r}")
    
    if cf_field:
        cf_type = field_type_map.get(cf_field, 0)
        cf_val, cf_desc = format_field_value(cf_field, cf_type, confidence)
        fields_to_write[cf_field] = cf_val
        print(f"  [{cf_field}] (type={cf_type}) -> {cf_desc}: {cf_val!r}")
    
    # 5. 构建 payload
    update_records = [{
        "record_id": record_id,
        "fields": fields_to_write
    }]
    
    print(f"\n完整 payload:")
    print(json.dumps(update_records, ensure_ascii=False, indent=2))
    
    # 6. 实际写入
    if dry_run:
        print(f"\n[DRY RUN] 未实际写入，仅展示 payload")
        return True
    
    try:
        feishu_client.update_bitable_records(app_token, table_id, update_records)
        print(f"\n✅ 写入成功: bugid={bugid}")
        return True
    except Exception as e:
        print(f"\n❌ 写入失败: {e}")
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="飞书多维表格写入模拟工具")
    parser.add_argument("--list-fields", action="store_true", help="列出所有字段及类型")
    parser.add_argument("--write", action="store_true", help="执行写入操作")
    parser.add_argument("--bugid", type=str, default="", help="Jira bugid")
    parser.add_argument("--rootcause", type=str, default="", help="rootcause 内容")
    parser.add_argument("--comment", type=str, default="", help="AI评论总结内容")
    parser.add_argument("--confidence", type=float, default=0.95, help="置信度(默认0.95)")
    parser.add_argument("--doc-url", type=str, default="", help="在线文档链接(可选)")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际写入")
    
    args = parser.parse_args()
    
    if args.list_fields:
        list_fields()
        return
    
    if args.write:
        if not args.bugid:
            print("ERROR: --bugid 参数必填")
            sys.exit(1)
        success = write_record(
            bugid=args.bugid,
            rootcause=args.rootcause,
            comment=args.comment,
            confidence=args.confidence,
            doc_url=args.doc_url,
            dry_run=args.dry_run
        )
        sys.exit(0 if success else 1)
    
    # 默认行为：列出字段
    list_fields()


if __name__ == "__main__":
    main()
