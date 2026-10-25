"""检查最近 9 个批次的 JIRA 号是否有重复"""
import sys, os
sys.path.insert(0, '.')
os.chdir('d:/program16')

from src.services.report_ops import _scan_all_batch_records
from collections import Counter

# 获取所有批次（本地+云端）
all_batches = _scan_all_batch_records(after_date='2026-10-01')

# 按日期+名称排序，取最近 9 个
all_batches.sort(key=lambda b: (b.get('date', ''), b.get('name', '')), reverse=True)

print(f'总共找到 {len(all_batches)} 个批次\n')

recent = all_batches[:9]
all_jiras = []
for i, b in enumerate(recent):
    jiras = b.get('jira_list', [])
    src = b.get('source', '')
    dt = b.get('date', '')
    nm = b.get('name', '')
    total = b.get('total', 0)
    print(f'{i+1}. [{dt}] {nm} | 来源: {src} | 总数: {total} | JIRA数: {len(jiras)}')
    all_jiras.extend(jiras)

# 检查跨批次重复
counter = Counter(all_jiras)
dupes = {k: v for k, v in counter.items() if v > 1}
print(f'\n--- 重复检查 ---')
print(f'9 批次总 JIRA 数: {len(all_jiras)}')
print(f'去重后: {len(counter)}')
if dupes:
    print(f'重复 JIRA: {len(dupes)} 个')
    for bid, cnt in sorted(dupes.items(), key=lambda x: -x[1]):
        in_batches = []
        for b in recent:
            if bid in b.get('jira_list', []):
                in_batches.append(f'[{b["date"]}] {b["name"]}')
        print(f'  {bid}: 出现 {cnt} 次')
        for bn in in_batches:
            print(f'    -> {bn}')
else:
    print('没有发现重复的 JIRA 号')
