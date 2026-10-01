"""查看云端触发时间所有数据表"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.clients import feishu_client
from src.web.server import _get_trigger_time_table_cfg

app_token, config_table_ids = _get_trigger_time_table_cfg()
print(f"Config 中的 table_ids: {config_table_ids}\n")

tables = feishu_client.list_bitable_tables(app_token)
print(f"云端实际数据表 ({len(tables)} 个):")
for t in tables:
    in_config = "[OK]" if t["table_id"] in config_table_ids else "[X]"
    print(f"  {t['name']:20s} -> {t['table_id']}  {in_config}")
