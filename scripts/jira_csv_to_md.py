"""
Jira CSV 导出文件转 Markdown 格式

使用方法:
    python scripts/jira_csv_to_md.py <csv文件路径> [输出文件路径]

示例:
    python scripts/jira_csv_to_md.py jira_export.csv
    python scripts/jira_csv_to_md.py jira_export.csv output.md
"""

import csv
import sys
from datetime import datetime
from pathlib import Path


def convert_jira_csv_to_md(csv_path: str, output_path: str = None) -> str:
    """将 Jira 导出的 CSV 文件转换为 Markdown 格式"""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"文件不存在: {csv_path}")

    # 默认输出路径：同目录下同名 .md 文件
    if output_path is None:
        output_path = str(csv_file.with_suffix(".md"))

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("CSV 文件为空，无数据可转换")
        return output_path

    headers = list(rows[0].keys())
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# Jira Bug 导出报告",
        "",
        f"> 导出时间：{now}  ",
        f"> 共 {len(rows)} 条记录",
        "",
    ]

    # 尝试找到关键字段作为标题
    key_field = None
    for candidate in ["问题关键字", "Key", "Issue Key", "issuekey"]:
        if candidate in headers:
            key_field = candidate
            break

    for row in rows:
        # 每个 Bug 独立章节
        bug_key = row.get(key_field, "").strip() if key_field else ""
        if bug_key:
            lines.append(f"## {bug_key}")
        else:
            lines.append(f"## Bug #{rows.index(row) + 1}")
        lines.append("")

        # 表格形式展示字段
        lines.append("| 字段 | 值 |")
        lines.append("|------|-----|")
        for header in headers:
            value = str(row.get(header, "")).strip()
            # 转义 Markdown 表格中的特殊字符
            value = value.replace("|", "\\|").replace("\n", " ").replace("\r", "")
            if not value:
                value = "-"
            lines.append(f"| **{header}** | {value} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"转换完成！共 {len(rows)} 条记录")
    print(f"输出文件: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    csv_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else None
    convert_jira_csv_to_md(csv_file, out_file)
