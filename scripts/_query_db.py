"""查询数据库数据分布"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 查看 case_info 总数
cursor.execute("SELECT COUNT(*) FROM case_info")
print(f"case_info 总数: {cursor.fetchone()[0]}")

# 查看有数据的列
cursor.execute("SELECT COUNT(*) FROM case_info WHERE vcu_number IS NOT NULL AND vcu_number != ''")
print(f"有 vcu_number: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM case_info WHERE analysis_result IS NOT NULL AND analysis_result != ''")
print(f"有 analysis_result: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM case_info WHERE case_status IS NOT NULL AND case_status != ''")
print(f"有 case_status: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM case_info WHERE error_type IS NOT NULL AND error_type != ''")
print(f"有 error_type: {cursor.fetchone()[0]}")

# 查看 case_status 分布（非空）
cursor.execute("SELECT case_status, COUNT(*) FROM case_info WHERE case_status IS NOT NULL AND case_status != '' GROUP BY case_status")
print("\ncase_status 分布:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 查看 analysis_result 分布（非空）
cursor.execute("SELECT analysis_result, COUNT(*) FROM case_info WHERE analysis_result IS NOT NULL AND analysis_result != '' GROUP BY analysis_result")
print("\nanalysis_result 分布:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 查看 trigger_source 分布
cursor.execute("SELECT trigger_source, COUNT(*) FROM case_info WHERE trigger_source IS NOT NULL AND trigger_source != '' GROUP BY trigger_source")
print("\ntrigger_source 分布:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 查看最新10条
cursor.execute("SELECT id, vcu_number, case_status, analysis_result, error_type, created_at FROM case_info ORDER BY id DESC LIMIT 10")
print("\n最新 10 条:")
for row in cursor.fetchall():
    print(f"  id={row[0]} vcu={row[1]} status={row[2]} result={row[3]} error={row[4]} created={row[5]}")

# 查看 trigger_times 表（如果有）
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%trigger%'")
trigger_tables = cursor.fetchall()
if trigger_tables:
    for t in trigger_tables:
        print(f"\n触发时间表: {t[0]}")
        cursor.execute(f"PRAGMA table_info({t[0]})")
        for col in cursor.fetchall():
            print(f"  {col[1]} ({col[2]})")

conn.close()
