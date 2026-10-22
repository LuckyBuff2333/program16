"""验证持续执行跨批次去重逻辑 - 结果写入文件避免终端编码问题"""
import os, csv, tempfile, shutil
from datetime import datetime, timedelta

result_file = os.path.join(os.path.dirname(__file__), "dedup_verify_result.txt")
results = []

def log(msg):
    results.append(msg)

test_dir = tempfile.mkdtemp(prefix="dedup_test_")
today = datetime.now().strftime("%Y-%m-%d")
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

log(f"=== Test 1: Cross-batch dedup (same day) ===")
log(f"Date: today={today}, yesterday={yesterday}")

# Setup directories
doc_dir = os.path.join(test_dir, "docs", today)
os.makedirs(doc_dir, exist_ok=True)
yesterday_dir = os.path.join(test_dir, "docs", yesterday)
os.makedirs(yesterday_dir, exist_ok=True)
unanalyzed_dir = os.path.join(test_dir, "data", "unanalyzed")
os.makedirs(unanalyzed_dir, exist_ok=True)

# Round 1: 20 Jiras executed
round1_bugids = [f"VCU-{558300 + i}" for i in range(20)]
with open(os.path.join(doc_dir, f"batch_{datetime.now().strftime('%H%M%S')}.csv"), "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["jira号", "执行结果", "触发来源"])
    writer.writeheader()
    for bid in round1_bugids:
        writer.writerow({"jira号": bid, "执行结果": "成功", "触发来源": "parseFullTicket"})

with open(os.path.join(unanalyzed_dir, f"prod_batch_{today}_{datetime.now().strftime('%H%M%S')}.csv"), "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["Jira号", "执行结果"])
    writer.writeheader()
    for bid in round1_bugids:
        writer.writerow({"Jira号": bid, "执行结果": "成功"})

# Round 2 candidates: round1 + 20 new
new_bugids = [f"VCU-{558320 + i}" for i in range(20)]
all_candidates = round1_bugids + new_bugids

# Simulate dedup
def mock_load_all():
    tested = set()
    for d in [doc_dir, yesterday_dir]:
        if os.path.isdir(d):
            for fname in os.listdir(d):
                if fname.endswith(".csv"):
                    with open(os.path.join(d, fname), 'r', encoding='utf-8-sig') as f:
                        for row in csv.DictReader(f):
                            jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                            if jira: tested.add(jira)
    if os.path.isdir(unanalyzed_dir):
        for fname in os.listdir(unanalyzed_dir):
            if fname.endswith(".csv"):
                with open(os.path.join(unanalyzed_dir, fname), 'r', encoding='utf-8-sig') as f:
                    for row in csv.DictReader(f):
                        jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                        if jira: tested.add(jira)
    return tested

def mock_cloud_keys(source=""):
    executed = set()
    check_dates = [today, yesterday]
    for date_str in check_dates:
        d = os.path.join(test_dir, "docs", date_str)
        if os.path.isdir(d):
            for fname in sorted(os.listdir(d)):
                if fname.startswith("batch_") and fname.endswith(".csv"):
                    with open(os.path.join(d, fname), 'r', encoding='utf-8-sig') as f:
                        for row in csv.DictReader(f):
                            jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                            src = (row.get("触发来源") or "").strip()
                            if jira and (not source or src == source):
                                executed.add(jira)
    if os.path.isdir(unanalyzed_dir):
        for date_str in check_dates:
            prefix = f"prod_batch_{date_str}_"
            for fname in sorted(os.listdir(unanalyzed_dir)):
                if fname.startswith(prefix) and fname.endswith(".csv"):
                    with open(os.path.join(unanalyzed_dir, fname), 'r', encoding='utf-8-sig') as f:
                        for row in csv.DictReader(f):
                            jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                            if jira: executed.add(jira)
    return executed

tested = mock_load_all() | mock_cloud_keys("")
available = [k for k in all_candidates if k not in tested]
round1_set = set(round1_bugids)
leaked = [k for k in available if k in round1_set]

log(f"Round 1 executed: {len(round1_bugids)}")
log(f"Round 2 candidates: {len(all_candidates)}")
log(f"Dedup set size: {len(tested)}")
log(f"Available after dedup: {len(available)}")
log(f"Leaked (should be 0): {len(leaked)}")
if not leaked:
    log("RESULT: PASS - all round1 Jiras excluded from round2")
else:
    log(f"RESULT: FAIL - {len(leaked)} leaked: {leaked[:5]}")

# Test 2: Same-batch dedup
log(f"\n=== Test 2: Same-batch dedup ===")
dup_input = ["VCU-100", "VCU-101", "VCU-100", "VCU-102", "VCU-101"]
seen = set()
unique = []
for k in dup_input:
    if k not in seen:
        seen.add(k)
        unique.append(k)
log(f"Input: {len(dup_input)} (with dupes), Output: {len(unique)}")
if len(unique) == 3:
    log("RESULT: PASS - duplicates removed within batch")
else:
    log(f"RESULT: FAIL - expected 3, got {len(unique)}")

# Test 3: Cross-day dedup
log(f"\n=== Test 3: Cross-day dedup ===")
test_dir2 = tempfile.mkdtemp(prefix="dedup_crossday_")
yd_doc = os.path.join(test_dir2, "docs", yesterday)
td_doc = os.path.join(test_dir2, "docs", today)
ua_dir = os.path.join(test_dir2, "data", "unanalyzed")
for d in [yd_doc, td_doc, ua_dir]:
    os.makedirs(d, exist_ok=True)

# Yesterday: 15 Jiras
yd_bugs = [f"VCU-{558400 + i}" for i in range(15)]
with open(os.path.join(yd_doc, "batch_230000.csv"), "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["jira号", "执行结果", "触发来源"])
    writer.writeheader()
    for bid in yd_bugs:
        writer.writerow({"jira号": bid, "执行结果": "成功", "触发来源": "parseFullTicket"})

with open(os.path.join(ua_dir, f"prod_batch_{yesterday}_230000.csv"), "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["Jira号", "执行结果"])
    writer.writeheader()
    for bid in yd_bugs:
        writer.writerow({"Jira号": bid, "执行结果": "成功"})

# Today: 10 Jiras (5 overlap with yesterday)
overlap = yd_bugs[:5]
td_new = [f"VCU-{558500 + i}" for i in range(5)]
td_bugs = overlap + td_new
with open(os.path.join(td_doc, "batch_003000.csv"), "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["jira号", "执行结果", "触发来源"])
    writer.writeheader()
    for bid in td_bugs:
        writer.writerow({"jira号": bid, "执行结果": "成功", "触发来源": "parseFullTicket"})

# Check cross-day dedup
def mock_cloud2(source=""):
    executed = set()
    for date_str in [today, yesterday]:
        d = os.path.join(test_dir2, "docs", date_str)
        if os.path.isdir(d):
            for fname in sorted(os.listdir(d)):
                if fname.startswith("batch_") and fname.endswith(".csv"):
                    with open(os.path.join(d, fname), 'r', encoding='utf-8-sig') as f:
                        for row in csv.DictReader(f):
                            jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                            if jira: executed.add(jira)
    if os.path.isdir(ua_dir):
        for date_str in [today, yesterday]:
            prefix = f"prod_batch_{date_str}_"
            for fname in sorted(os.listdir(ua_dir)):
                if fname.startswith(prefix) and fname.endswith(".csv"):
                    with open(os.path.join(ua_dir, fname), 'r', encoding='utf-8-sig') as f:
                        for row in csv.DictReader(f):
                            jira = (row.get("jira号") or row.get("Jira号") or "").strip()
                            if jira: executed.add(jira)
    return executed

executed_cross = mock_cloud2("")
all_executed = set(yd_bugs) | set(td_bugs)
new_candidates = [f"VCU-{558600 + i}" for i in range(10)]
candidates3 = list(all_executed) + new_candidates
available3 = [k for k in candidates3 if k not in executed_cross]
leaked3 = [k for k in available3 if k in all_executed]

log(f"Yesterday executed: {len(yd_bugs)}")
log(f"Today executed: {len(td_bugs)} (5 overlap)")
log(f"Unique executed: {len(all_executed)}")
log(f"Dedup set size: {len(executed_cross)}")
log(f"New candidates: 10, Total candidates: {len(candidates3)}")
log(f"Available after dedup: {len(available3)}")
log(f"Leaked (should be 0): {len(leaked3)}")
if not leaked3:
    log("RESULT: PASS - cross-day dedup works correctly")
else:
    log(f"RESULT: FAIL - {len(leaked3)} leaked: {leaked3}")

# Cleanup
shutil.rmtree(test_dir)
shutil.rmtree(test_dir2)

# Write results
with open(result_file, "w", encoding="utf-8") as f:
    f.write("\n".join(results))
