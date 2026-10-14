"""导出 FastAPI OpenAPI schema 为 JSON 文件

用法：py scripts/dump_openapi.py
输出：frontend/src/types/api.d.ts（通过 openapi-typescript 转换）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.app import create_app

app = create_app()
schema = app.openapi()

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "src", "types")
os.makedirs(out_dir, exist_ok=True)

schema_path = os.path.join(out_dir, "openapi.json")
with open(schema_path, "w", encoding="utf-8") as f:
    json.dump(schema, f, ensure_ascii=False, indent=2)

print(f"OpenAPI schema dumped to: {schema_path}")
print(f"Components: {list(schema.get('components', {}).get('schemas', {}).keys())}")
print(f"Paths: {len(schema.get('paths', {}))}")
