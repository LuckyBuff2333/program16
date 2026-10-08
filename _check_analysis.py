"""临时脚本：检查数据库和CSV中的分析记录时间分布"""
import sqlite3
import os
import csv
from collections import Counter

# 检查数据库
db_path = "d:/program16/data/app.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"数据库表: {tables}")
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {t}")
        count = cursor.fetchone()[0]
        print(f"  {t}: {count} 条记录")
    conn.close()

# 检查 CSV 批量执行记录
csv_dir = "d:/program16/data"
for root, dirs, files in os.walk(csv_dir):
    for f in files:
        if f.endswith(".csv"):
            path = os.path.join(root, f)
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    rows = list(reader)
                    if rows:
                        # 找到日期相关列
                        date_cols = [c for c in rows[0].keys() if any(k in c for k in ["日期", "时间", "date", "time", "完成"])]
                        print(f"\nCSV: {f} ({len(rows)} 行)")
                        print(f"  列名: {list(rows[0].keys())[:10]}")
                        if date_cols:
                            print(f"  日期列: {date_cols}")
                            for col in date_cols[:2]:
                                dates = [r.get(col, "")[:10] for r in rows if r.get(col)]
                                if dates:
                                    counter = Counter(dates)
                                    print(f"  [{col}] 日期分布:")
                                    for d in sorted(counter.keys())[-15:]:
                                        print(f"    {d}: {counter[d]} 条")
            except Exception as e:
                print(f"  读取 {f} 失败: {e}")
