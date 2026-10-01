# -*- coding: utf-8 -*-
import json
c = json.load(open(r'e:\program16\data\video_time_cache.json', 'r', encoding='utf-8'))
print(f"Total cache entries: {len(c)}")
print(f"Failed entries: {sum(1 for v in c.values() if not v.get('time'))}")
print("\nFailed entries:")
for k, v in c.items():
    if not v.get('time'):
        print(f"  {k}: reason={v.get('reason', 'N/A')}")
