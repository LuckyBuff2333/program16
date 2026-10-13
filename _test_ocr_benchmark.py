"""批量对比测试：EasyOCR vs RapidOCR 视频帧触发时间正确率
两阶段：Phase1 串行下载 → Phase2 串行帧提取+OCR（GPU安全）
"""
import os, sys, json, time, re, logging, tempfile, shutil
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger('ocr_bench')

import httpx
from src.web.server import (
    load_config, _extract_video_frames_gpu,
    _get_ocr_reader, _rapid_ocr_readtext,
    _fix_ocr_missing_colon, _preprocess_ocr_datetime, _normalize_ocr_time,
)
from src.clients.jira_client import fetch_issue

cfg = load_config().get('jira_api', {})
headers = {}
token = cfg.get('token', '')
if token:
    headers['Authorization'] = f"Bearer {token}"

TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.,\-]?\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)')
TIME_ONLY_RE = re.compile(r'(?<!\d)(\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)(?!\d)')

def extract_time_from_text(text):
    text = _fix_ocr_missing_colon(text)
    text = _preprocess_ocr_datetime(text)
    m = TIME_FULL_RE.search(text)
    if m: return _normalize_ocr_time(m.group(1)), None
    m = TIME_ONLY_RE.search(text)
    if m: return None, _normalize_ocr_time(m.group(1))
    return None, None

def time_matches(expected, full_time, partial_time):
    if not expected: return False
    if full_time and expected.startswith(full_time[:10]):
        return expected[11:16] == (full_time[11:16] if len(full_time) > 15 else '')
    if partial_time:
        exp_hm = expected[11:16] if len(expected) > 15 else expected[:5]
        return partial_time[:5] == exp_hm
    return False

# ─── 选取记录 ───
with open('data/video_time_cache.json', 'r') as f:
    cache = json.load(f)
candidates = []
for key, val in cache.items():
    t = val.get('time', '')
    if re.match(r'\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}', t):
        parts = key.split(':', 1)
        if len(parts) == 2:
            candidates.append({'bugid': parts[0], 'video_name': parts[1],
                              'expected_time': t, 'extracted_at': val.get('extracted_at', '')})
candidates.sort(key=lambda x: x['extracted_at'], reverse=True)
test_set = candidates[:20]

# ─── Phase 1: 串行下载所有视频 ───
tmp_dir = tempfile.mkdtemp()
logger.info("Phase 1: 下载 %d 个视频...", len(test_set))
downloaded = {}  # bugid -> video_path

for idx, item in enumerate(test_set):
    bugid = item['bugid']
    try:
        issue = fetch_issue(bugid)
        attachments = issue.get('fields', {}).get('attachment', [])
        video_att = [a for a in attachments if a.get('filename', '') == item['video_name']]
        if not video_att:
            video_att = [a for a in attachments if (a.get('filename', '') or '').lower().endswith(('.mp4', '.mov', '.avi'))]
        if not video_att:
            logger.warning("  [%d/%d] %s 无视频", idx+1, len(test_set), bugid)
            continue
        video_url = video_att[0]['content']
        video_path = os.path.join(tmp_dir, f'{bugid}.bin')
        with httpx.stream('GET', video_url, headers=headers, timeout=60, verify=False, follow_redirects=True) as resp:
            with open(video_path, 'wb') as f:
                for chunk in resp.iter_bytes(chunk_size=1024*1024):
                    f.write(chunk)
        downloaded[bugid] = video_path
        logger.info("  [%d/%d] %s ✓ (%.1fMB)", idx+1, len(test_set), bugid, os.path.getsize(video_path)/1024/1024)
    except Exception as e:
        logger.warning("  [%d/%d] %s 下载失败: %s", idx+1, len(test_set), bugid, e)

logger.info("Phase 1 完成: %d/%d 下载成功", len(downloaded), len(test_set))

# ─── Phase 2: 串行帧提取 + OCR ───
logger.info("Phase 2: 帧提取 + OCR 对比...")
easy_reader = _get_ocr_reader()
results = []
t_start = time.time()

for idx, item in enumerate(test_set):
    bugid = item['bugid']
    expected = item['expected_time']
    row = {'bugid': bugid, 'expected': expected, 'video': item['video_name'],
           'easy_ok': False, 'rapid_ok': False}

    if bugid not in downloaded:
        row['error'] = 'no_download'
        results.append(row)
        continue

    video_path = downloaded[bugid]
    frames = _extract_video_frames_gpu(video_path, positions=[0], use_gpu=True) or []
    if not frames:
        row['error'] = 'no_frame'
        results.append(row)
        continue

    frame = frames[0][1]

    # EasyOCR
    t0 = time.time()
    try:
        easy_results = easy_reader.readtext(frame, canvas_size=2560, mag_ratio=1.5,
                                             text_threshold=0.25, low_text=0.3)
    except:
        easy_results = easy_reader.readtext(frame)
    easy_elapsed = time.time() - t0
    easy_text = ' '.join(r[1] for r in easy_results if len(r) > 1)
    easy_full, easy_partial = extract_time_from_text(easy_text)
    row['easy_ok'] = time_matches(expected, easy_full, easy_partial)
    row['easy_result'] = easy_full or easy_partial or '(空)'
    row['easy_time'] = round(easy_elapsed, 2)
    row['easy_conf'] = round(sum(r[2] for r in easy_results if len(r) > 2) / max(len(easy_results), 1), 3)

    # RapidOCR
    t0 = time.time()
    rapid_results = _rapid_ocr_readtext(frame)
    rapid_elapsed = time.time() - t0
    rapid_text = ' '.join(r[1] for r in rapid_results if len(r) > 1)
    rapid_full, rapid_partial = extract_time_from_text(rapid_text)
    row['rapid_ok'] = time_matches(expected, rapid_full, rapid_partial)
    row['rapid_result'] = rapid_full or rapid_partial or '(空)'
    row['rapid_time'] = round(rapid_elapsed, 2)
    row['rapid_conf'] = round(sum(r[2] for r in rapid_results if len(r) > 2) / max(len(rapid_results), 1), 3)

    e_s = "✓" if row['easy_ok'] else "✗"
    r_s = "✓" if row['rapid_ok'] else "✗"
    logger.info("[%d/%d] %s 期望:%s | Easy%s %.2fs conf=%.2f → %s | Rapid%s %.2fs conf=%.2f → %s",
                idx+1, len(test_set), bugid, expected,
                e_s, easy_elapsed, row['easy_conf'], row['easy_result'],
                r_s, rapid_elapsed, row['rapid_conf'], row['rapid_result'])
    results.append(row)

total_elapsed = time.time() - t_start
shutil.rmtree(tmp_dir, ignore_errors=True)

# ─── 汇总 ───
valid = [r for r in results if 'error' not in r]
total = len(valid)
easy_ok = sum(1 for r in valid if r['easy_ok'])
rapid_ok = sum(1 for r in valid if r['rapid_ok'])
both_ok = sum(1 for r in valid if r['easy_ok'] and r['rapid_ok'])
both_fail = sum(1 for r in valid if not r['easy_ok'] and not r['rapid_ok'])
only_easy = sum(1 for r in valid if r['easy_ok'] and not r['rapid_ok'])
only_rapid = sum(1 for r in valid if not r['easy_ok'] and r['rapid_ok'])

print("\n" + "="*120)
print(f"{'#':<4} {'BugID':<14} {'期望时间':<20} {'Easy':<5} {'Easy结果':<16} {'Easy耗时':<8} {'Conf':<8} {'Rapid':<5} {'Rapid结果':<16} {'Rapid耗时':<8} {'Conf'}")
print("="*120)
for i, r in enumerate(results):
    if 'error' in r:
        print(f"{i+1:<4} {r['bugid']:<14} {r['expected']:<20} {'SKIP':<5} {r.get('error','')[:20]:<16}")
        continue
    e_s = "✓" if r['easy_ok'] else "✗"
    r_s = "✓" if r['rapid_ok'] else "✗"
    print(f"{i+1:<4} {r['bugid']:<14} {r['expected']:<20} {e_s:<5} {r['easy_result']:<16} {r['easy_time']:<8.2f} {r['easy_conf']:<8.3f} {r_s:<5} {r['rapid_result']:<16} {r['rapid_time']:<8.2f} {r['rapid_conf']}")

print("="*120)
e_avg_c = sum(r.get('easy_conf', 0) for r in valid) / max(total, 1)
r_avg_c = sum(r.get('rapid_conf', 0) for r in valid) / max(total, 1)
e_avg_t = sum(r.get('easy_time', 0) for r in valid) / max(total, 1)
r_avg_t = sum(r.get('rapid_time', 0) for r in valid) / max(total, 1)
print(f"\n=== 对比汇总（有效 {total}/{len(test_set)} 条，总耗时 {total_elapsed:.1f}s）===")
print(f"  EasyOCR  正确: {easy_ok}/{total} ({easy_ok/total*100:.1f}%)  avg_conf={e_avg_c:.3f}  avg_time={e_avg_t:.2f}s")
print(f"  RapidOCR 正确: {rapid_ok}/{total} ({rapid_ok/total*100:.1f}%)  avg_conf={r_avg_c:.3f}  avg_time={r_avg_t:.2f}s")
print(f"\n  两者都✓: {both_ok}  两者都✗: {both_fail}  仅Easy✓: {only_easy}  仅Rapid✓: {only_rapid}")

with open('logs/ocr_benchmark_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n详细结果 → logs/ocr_benchmark_results.json")
