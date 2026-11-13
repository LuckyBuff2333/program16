"""
批量 OCR 对比测试：RapidOCR PP-OCRv5 vs PaddleOCR PP-OCRv6
流程：飞书多维表格查成功 → JIRA 查含视频 → 下载视频提取帧 → 双 OCR 对比
"""
import os
import sys
import time
import json
import re
import tempfile
import shutil
import requests
import numpy as np
import cv2
from collections import Counter

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

# ── 配置 ──
JIRA_BASE = "https://jira-patac.apps.saic-gm.com"
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")
JIRA_HEADERS = {"Authorization": f"Bearer {JIRA_TOKEN}", "Accept": "application/json"}
TIME_RE = re.compile(r'(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')
FULL_TIME_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.,\-]?\d{1,2}[.:,;]\d{2}(?:[.:,;]\d{2})?)')
MAX_JIRAS = 50
CACHE_DIR = os.path.join(PROJ_ROOT, "_verify_tmp", "ocr_compare_cache")


def _bitable_text(val):
    """扁平化飞书多维表格字段值"""
    if val is None:
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        first = val[0]
        if isinstance(first, dict) and "text" in first:
            return "".join(seg.get("text", "") for seg in val)
        if isinstance(first, str):
            return ", ".join(val)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, dict):
        return val.get("value", json.dumps(val, ensure_ascii=False))
    return str(val)


def query_successful_jiras():
    """从飞书多维表格查询分析成功的 Jira 号"""
    from src.config import load_config
    from src.clients import feishu_client

    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        print("[ERROR] 飞书 app_token 或 table_id 未配置")
        return []

    print(f"[飞书] 查询多维表格: app={app_token}, table={table_id}")
    records = feishu_client.list_bitable_records(app_token, table_id, page_size=500)
    print(f"[飞书] 获取 {len(records)} 条记录")

    # 筛选分析成功的记录
    success_jiras = []
    seen = set()
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get("jira号", "")).strip()
        result = _bitable_text(fields.get("分析结果", "")).strip()
        if not jira_no or jira_no in seen:
            continue
        if result == "成功":
            success_jiras.append(jira_no)
            seen.add(jira_no)

    print(f"[飞书] 分析成功: {len(success_jiras)} 个 Jira")
    return success_jiras


def find_jiras_with_videos(jira_list):
    """从 JIRA API 检查哪些工单含视频附件，返回 [(jira_no, video_url, video_name)]"""
    results = []
    total = len(jira_list)
    for i, jira_no in enumerate(jira_list):
        if len(results) >= MAX_JIRAS:
            break
        if (i + 1) % 10 == 0:
            print(f"[JIRA] 检查进度: {i+1}/{total}, 已找到 {len(results)} 个含视频")
        try:
            url = f"{JIRA_BASE}/rest/api/2/issue/{jira_no}"
            resp = requests.get(url, headers=JIRA_HEADERS, timeout=15, verify=False)
            if resp.status_code != 200:
                continue
            data = resp.json()
            attachments = data.get("fields", {}).get("attachment", [])
            for att in attachments:
                fname = att.get("filename", "")
                if fname.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")):
                    video_url = att.get("content", "")
                    if video_url:
                        results.append((jira_no, video_url, fname))
                        break  # 只取第一个视频
        except Exception as e:
            continue
    print(f"[JIRA] 共找到 {len(results)} 个含视频的 Jira")
    return results


def download_and_extract_frame(video_url, video_name):
    """下载视频并提取第一帧（使用 PyAV）"""
    import av
    tmp_dir = tempfile.mkdtemp()
    try:
        video_path = os.path.join(tmp_dir, "video.bin")
        resp = requests.get(video_url, headers=JIRA_HEADERS, timeout=120,
                            verify=False, stream=True)
        if resp.status_code != 200:
            return None
        with open(video_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        # 用 PyAV 提取第一帧
        container = av.open(video_path)
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            img = frame.to_ndarray(format="bgr24")
            container.close()
            return img
        container.close()
    except Exception as e:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def run_rapid_ocr(engine, img):
    """RapidOCR 识别"""
    t0 = time.perf_counter()
    result = engine(img)
    elapsed = time.perf_counter() - t0
    items = []
    if result and result[0]:
        for entry in result[0]:
            items.append({"text": str(entry[1]), "conf": float(entry[2])})
    return items, elapsed


def run_paddle_ocr(pipe, img):
    """PaddleOCR PP-OCRv6 识别"""
    t0 = time.perf_counter()
    results = list(pipe.predict(img))
    elapsed = time.perf_counter() - t0
    items = []
    if results:
        r = results[0]
        texts = r.get('rec_texts', []) if hasattr(r, 'get') else getattr(r, 'rec_texts', [])
        scores = r.get('rec_scores', []) if hasattr(r, 'get') else getattr(r, 'rec_scores', [])
        for txt, conf in zip(texts, scores):
            items.append({"text": str(txt), "conf": float(conf)})
    return items, elapsed


def extract_time_from_items(items):
    """从 OCR 结果中提取时间文本"""
    times = []
    for item in items:
        m = TIME_RE.search(item["text"])
        if m:
            times.append(m.group(1))
        m2 = FULL_TIME_RE.search(item["text"])
        if m2:
            times.append(m2.group(1))
    return times


def init_engines():
    """初始化两个 OCR 引擎"""
    import torch  # 先导入 torch 避免 DLL 冲突
    print(f"[引擎] torch: {torch.__version__}")

    # RapidOCR
    from rapidocr_onnxruntime import RapidOCR
    import yaml
    cfg_path = os.path.join(PROJ_ROOT, "models", "ppocrv5", "rapidocr_v5.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        ycfg = yaml.safe_load(f)
    model_dir = os.path.join(PROJ_ROOT, "models", "ppocrv5")
    for sec, fname in [("Det", "det.onnx"), ("Cls", "cls.onnx"), ("Rec", "rec.onnx")]:
        if sec in ycfg:
            ycfg[sec]["model_path"] = os.path.join(model_dir, fname)
            ycfg[sec]["use_cuda"] = False
    if "Rec" in ycfg:
        ycfg["Rec"]["rec_keys_path"] = os.path.join(model_dir, "ppocrv5_dict.txt")
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rapidocr_compare.yaml")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)
    rapid = RapidOCR(config_path=tmp_cfg)
    print("[引擎] RapidOCR PP-OCRv5 初始化完成")

    # PaddleOCR PP-OCRv6
    from paddlex.inference import create_pipeline
    from paddlex.inference.models.runners.paddle_static.config.pp_option import PaddlePredictorOption
    pp = PaddlePredictorOption(run_mode='paddle_fp32')
    paddle_pipe = create_pipeline(pipeline='OCR', pp_option=pp)
    print("[引擎] PaddleOCR PP-OCRv6 初始化完成")

    return rapid, paddle_pipe


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    os.makedirs(CACHE_DIR, exist_ok=True)

    print("=" * 80)
    print("  批量 OCR 对比测试（50 个 Jira 视频首帧）")
    print("  RapidOCR PP-OCRv5 vs PaddleOCR PP-OCRv6")
    print("=" * 80)

    # 1. 初始化引擎
    print("\n── 1. 初始化 OCR 引擎 ──")
    rapid, paddle_pipe = init_engines()

    # 2. 从飞书查询成功的 Jira
    print("\n── 2. 查询飞书多维表格 ──")
    success_jiras = query_successful_jiras()
    if not success_jiras:
        print("[ERROR] 无成功记录，退出")
        return

    # 3. 从 JIRA 检查含视频的工单
    print(f"\n── 3. 检查 JIRA 视频附件（目标 {MAX_JIRAS} 个）──")
    video_jiras = find_jiras_with_videos(success_jiras[:300])  # 检查前300个
    if not video_jiras:
        print("[ERROR] 无含视频的工单，退出")
        return

    # 4. 逐个下载视频、提取帧、对比 OCR
    print(f"\n── 4. 批量对比测试（{len(video_jiras)} 个视频）──")
    all_results = []
    rapid_time_hits = 0
    paddle_time_hits = 0
    rapid_total_conf = 0
    paddle_total_conf = 0
    rapid_total_time = 0
    paddle_total_time = 0
    rapid_detect_count = 0
    paddle_detect_count = 0

    for idx, (jira_no, video_url, video_name) in enumerate(video_jiras):
        print(f"\n[{idx+1}/{len(video_jiras)}] {jira_no} - {video_name}")

        # 检查缓存
        cache_path = os.path.join(CACHE_DIR, f"{jira_no}.npy")
        if os.path.exists(cache_path):
            img = np.load(cache_path)
            print(f"  帧缓存命中")
        else:
            img = download_and_extract_frame(video_url, video_name)
            if img is None:
                print(f"  视频下载/解码失败，跳过")
                continue
            np.save(cache_path, img)
            print(f"  帧尺寸: {img.shape[1]}x{img.shape[0]}")

        # RapidOCR
        r_items, r_time = run_rapid_ocr(rapid, img)
        r_times = extract_time_from_items(r_items)
        r_avg_conf = np.mean([i["conf"] for i in r_items]) if r_items else 0
        r_has_time = len(r_times) > 0

        # PaddleOCR
        p_items, p_time = run_paddle_ocr(paddle_pipe, img)
        p_times = extract_time_from_items(p_items)
        p_avg_conf = np.mean([i["conf"] for i in p_items]) if p_items else 0
        p_has_time = len(p_times) > 0

        # 统计
        if r_has_time:
            rapid_time_hits += 1
        if p_has_time:
            paddle_time_hits += 1
        rapid_total_conf += r_avg_conf
        paddle_total_conf += p_avg_conf
        rapid_total_time += r_time
        paddle_total_time += p_time
        rapid_detect_count += len(r_items)
        paddle_detect_count += len(p_items)

        r_time_str = ", ".join(r_times) if r_times else "-"
        p_time_str = ", ".join(p_times) if p_times else "-"

        print(f"  Rapid:  {len(r_items)} 条 | 时间: {r_time_str} | conf={r_avg_conf:.3f} | {r_time:.2f}s")
        print(f"  Paddle: {len(p_items)} 条 | 时间: {p_time_str} | conf={p_avg_conf:.3f} | {p_time:.2f}s")

        all_results.append({
            "jira": jira_no,
            "video": video_name,
            "rapid_items": len(r_items),
            "paddle_items": len(p_items),
            "rapid_time_hit": r_has_time,
            "paddle_time_hit": p_has_time,
            "rapid_times": r_times,
            "paddle_times": p_times,
            "rapid_conf": r_avg_conf,
            "paddle_conf": p_avg_conf,
            "rapid_elapsed": r_time,
            "paddle_elapsed": p_time,
        })

    # 5. 汇总报告
    n = len(all_results)
    if n == 0:
        print("\n[ERROR] 无有效结果，退出")
        return

    print(f"\n\n{'='*80}")
    print(f"  汇总报告（{n} 个视频首帧）")
    print(f"{'='*80}")

    print(f"\n{'Jira号':<16} {'Rapid时间':>8} {'Paddle时间':>10} {'Rapid置信':>10} {'Paddle置信':>10} {'Rapid耗时':>10} {'Paddle耗时':>10}")
    print("-" * 80)
    for r in all_results:
        r_mark = "✓" if r["rapid_time_hit"] else "✗"
        p_mark = "✓" if r["paddle_time_hit"] else "✗"
        print(f"{r['jira']:<16} {r_mark:>8} {p_mark:>10} {r['rapid_conf']:>10.3f} {r['paddle_conf']:>10.3f} "
              f"{r['rapid_elapsed']:>9.2f}s {r['paddle_elapsed']:>9.2f}s")

    print("-" * 80)
    print(f"\n── 对比汇总 ──")
    print(f"时间命中率:    RapidOCR = {rapid_time_hits}/{n} ({rapid_time_hits/n*100:.1f}%)  |  "
          f"PaddleOCR = {paddle_time_hits}/{n} ({paddle_time_hits/n*100:.1f}%)")
    print(f"平均置信度:    RapidOCR = {rapid_total_conf/n:.3f}  |  "
          f"PaddleOCR = {paddle_total_conf/n:.3f}")
    print(f"平均耗时:      RapidOCR = {rapid_total_time/n:.3f}s  |  "
          f"PaddleOCR = {paddle_total_time/n:.3f}s")
    print(f"平均检测文本数: RapidOCR = {rapid_detect_count/n:.1f}  |  "
          f"PaddleOCR = {paddle_detect_count/n:.1f}")

    # 差异分析
    only_rapid = [r for r in all_results if r["rapid_time_hit"] and not r["paddle_time_hit"]]
    only_paddle = [r for r in all_results if r["paddle_time_hit"] and not r["rapid_time_hit"]]
    both_hit = [r for r in all_results if r["rapid_time_hit"] and r["paddle_time_hit"]]
    both_miss = [r for r in all_results if not r["rapid_time_hit"] and not r["paddle_time_hit"]]

    print(f"\n── 差异分析 ──")
    print(f"两者都命中: {len(both_hit)}  |  两者都未命中: {len(both_miss)}")
    print(f"仅 Rapid 命中: {len(only_rapid)}  |  仅 Paddle 命中: {len(only_paddle)}")
    if only_rapid:
        print(f"  仅 Rapid 命中的 Jira: {[r['jira'] for r in only_rapid]}")
    if only_paddle:
        print(f"  仅 Paddle 命中的 Jira: {[r['jira'] for r in only_paddle]}")

    # 保存详细结果
    result_path = os.path.join(PROJ_ROOT, "reports", "ocr_compare_result.json")
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {result_path}")


if __name__ == "__main__":
    main()
