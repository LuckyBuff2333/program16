"""
GLM-OCR + ROI vs RapidOCR + ROI 大样本对比（90 条视频帧）
先下载缓存帧，再两引擎分别识别，逐帧对比
"""
import os, sys, time, json, re, tempfile, shutil
import numpy as np
import cv2
import requests

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

TARGET = 90
CACHE_DIR = os.path.join(PROJ_ROOT, "_verify_tmp", f"compare_cache_{TARGET}")
TIME_RE = re.compile(r'(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')

ROI_REGIONS = [
    ("right_clock",  0.55, 0.10, 0.95, 0.55),
    ("right_upper",  0.44, 0.00, 1.00, 0.46),
    ("top_bar",      0.00, 0.00, 1.00, 0.17),
    ("center_right", 0.50, 0.32, 1.00, 0.73),
    ("right_lower",  0.58, 0.60, 1.00, 1.00),
    ("left_upper",   0.00, 0.00, 0.50, 0.48),
    ("left_lower",   0.00, 0.38, 0.60, 1.00),
]


def _bitable_text(val):
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(
            item.get("text", "") or str(item.get("value", ""))
            if isinstance(item, dict) else str(item) for item in val)
    if isinstance(val, dict):
        return val.get("value", json.dumps(val, ensure_ascii=False))
    return str(val)


def fetch_success_jiras():
    """从飞书查成功记录"""
    from src.config import load_config
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    records = feishu_client.list_bitable_records(app_token, table_id, page_size=500)
    print(f"[飞书] {len(records)} 条记录")
    success, seen = [], set()
    for rec in records:
        fields = rec.get("fields", {})
        jira = _bitable_text(fields.get("jira号", "")).strip()
        result = _bitable_text(fields.get("分析结果", "")).strip()
        if not jira or jira in seen or result != "成功":
            continue
        success.append(jira)
        seen.add(jira)
    print(f"[飞书] 成功: {len(success)} 个")
    return success


def find_videos(jira_list, target=TARGET):
    """从 JIRA 找含视频的工单"""
    from src.config import load_config
    cfg = load_config().get("jira_api", {})
    token, base = cfg.get("token", ""), cfg.get("url", "").replace("/rest/api/2/issue", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    results = []
    for i, jira in enumerate(jira_list):
        if len(results) >= target:
            break
        if (i + 1) % 50 == 0:
            print(f"[JIRA] 扫描 {i+1}/{len(jira_list)}, 已找到 {len(results)} 个含视频")
        try:
            resp = requests.get(f"{base}/rest/api/2/issue/{jira}",
                                headers=headers, timeout=15, verify=False)
            if resp.status_code != 200:
                continue
            for att in resp.json().get("fields", {}).get("attachment", []):
                fn = att.get("filename", "")
                if fn.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")):
                    results.append((jira, att.get("content", ""), fn))
                    break
        except Exception:
            continue
    print(f"[JIRA] 共 {len(results)} 个含视频")
    return results


def download_frame(video_url, jira_token):
    """下载视频首帧"""
    import av
    tmp_dir = tempfile.mkdtemp()
    try:
        vpath = os.path.join(tmp_dir, "v.bin")
        resp = requests.get(video_url, headers={"Authorization": f"Bearer {jira_token}"},
                            timeout=120, verify=False, stream=True)
        if resp.status_code != 200:
            return None
        with open(vpath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        container = av.open(vpath)
        for frame in container.decode(container.streams.video[0]):
            img = frame.to_ndarray(format="bgr24")
            container.close()
            return img
        container.close()
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def get_roi_crops(frame, enlarge=1):
    """ROI 裁剪"""
    h, w = frame.shape[:2]
    crops = []
    for name, rx1, ry1, rx2, ry2 in ROI_REGIONS:
        x1, y1, x2, y2 = int(w*rx1), int(h*ry1), int(w*rx2), int(h*ry2)
        if x2-x1 < 40 or y2-y1 < 12:
            continue
        crop = frame[y1:y2, x1:x2]
        if enlarge > 1:
            ch, cw = crop.shape[:2]
            crop = cv2.resize(crop, (cw*enlarge, ch*enlarge), interpolation=cv2.INTER_CUBIC)
        crops.append((name, crop))
    return crops


def run_rapid(frames):
    """RapidOCR PP-OCRv5 GPU"""
    import yaml
    from rapidocr_onnxruntime import RapidOCR
    cfg_path = os.path.join(PROJ_ROOT, "models", "ppocrv5", "rapidocr_v5.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        ycfg = yaml.safe_load(f)
    model_dir = os.path.join(PROJ_ROOT, "models", "ppocrv5")
    for sec, fname in [("Det", "det.onnx"), ("Cls", "cls.onnx"), ("Rec", "rec.onnx")]:
        if sec in ycfg:
            ycfg[sec]["model_path"] = os.path.join(model_dir, fname)
            ycfg[sec]["use_cuda"] = True
    if "Rec" in ycfg:
        ycfg["Rec"]["rec_keys_path"] = os.path.join(model_dir, "ppocrv5_dict.txt")
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rapid_90.yaml")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)
    engine = RapidOCR(config_path=tmp_cfg)
    engine(np.random.randint(0, 255, (128, 256, 3), dtype=np.uint8))
    print("  RapidOCR 就绪")

    results = []
    for idx, (jira, img) in enumerate(frames):
        crops = get_roi_crops(img, enlarge=3)
        t0 = time.perf_counter()
        all_texts = []
        full_r = engine(img)
        if full_r and full_r[0]:
            all_texts.extend([str(e[1]) for e in full_r[0]])
        for rname, crop in crops:
            r = engine(crop)
            if r and r[0]:
                all_texts.extend([str(e[1]) for e in r[0]])
        elapsed = time.perf_counter() - t0
        found = [TIME_RE.search(t).group(1) for t in all_texts if TIME_RE.search(t)]
        results.append({"jira": jira, "hit": len(found) > 0, "times": found[:5],
                         "items": len(all_texts), "elapsed": round(elapsed, 4)})
        if (idx + 1) % 10 == 0:
            hits_so_far = sum(1 for r in results if r["hit"])
            print(f"    [{idx+1:>3}/{len(frames)}] 当前命中: {hits_so_far}/{idx+1}")
    return results


def run_glm_roi(frames):
    """GLM-OCR + ROI（原尺寸，无放大）"""
    import torch
    from src.services.glm_ocr import ocr_text
    # 预热
    ocr_text(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8), max_new_tokens=8)
    print("  GLM-OCR 就绪")

    results = []
    for idx, (jira, img) in enumerate(frames):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        all_times = []
        # 先全帧
        text = ocr_text(img, max_new_tokens=64)
        all_times.extend(TIME_RE.findall(text) if text else [])
        if not all_times:
            # 全帧未命中，尝试 ROI
            for rname, crop in get_roi_crops(img, enlarge=1):
                text = ocr_text(crop, max_new_tokens=32)
                found = TIME_RE.findall(text) if text else []
                all_times.extend(found)
                if found:
                    break
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        results.append({"jira": jira, "hit": len(all_times) > 0, "times": all_times[:5],
                         "text": (text or "")[:200], "elapsed": round(elapsed, 4)})
        if (idx + 1) % 10 == 0:
            hits_so_far = sum(1 for r in results if r["hit"])
            print(f"    [{idx+1:>3}/{len(frames)}] 当前命中: {hits_so_far}/{idx+1}")
    return results


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    import torch

    print(f"{'='*70}")
    print(f"  GLM-OCR+ROI vs RapidOCR+ROI  ({TARGET} 条大样本对比)")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    print(f"{'='*70}")

    # ── 1. 准备缓存帧 ──
    os.makedirs(CACHE_DIR, exist_ok=True)
    cached = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith(".npy"))
    print(f"已有缓存: {len(cached)} 帧")

    if len(cached) < TARGET:
        print(f"\n── 下载视频首帧（目标 {TARGET}）──")
        from src.config import load_config
        success = fetch_success_jiras()
        videos = find_videos(success[:800], target=TARGET)
        jira_token = load_config().get("jira_api", {}).get("token", "")
        dl_count = 0
        for jira, video_url, vname in videos:
            cache_path = os.path.join(CACHE_DIR, f"{jira}.npy")
            if os.path.exists(cache_path):
                continue
            print(f"  下载: {jira} ({vname})...", end=" ", flush=True)
            img = download_frame(video_url, jira_token)
            if img is not None:
                np.save(cache_path, img)
                dl_count += 1
                print(f"{img.shape[1]}x{img.shape[0]}")
            else:
                print("失败")
            if dl_count + len(cached) >= TARGET:
                break
        print(f"  新下载: {dl_count}")

    # 加载帧
    frames = []
    for fn in sorted(f for f in os.listdir(CACHE_DIR) if f.endswith(".npy"))[:TARGET]:
        frames.append((fn.replace(".npy", ""), np.load(os.path.join(CACHE_DIR, fn))))
    n = len(frames)
    print(f"\n有效样本: {n}")
    if n == 0:
        return

    # ── 2. RapidOCR ──
    print(f"\n{'─'*70}")
    print(f"  [1/2] RapidOCR PP-OCRv5 (全帧+ROI 3x, GPU)")
    print(f"{'─'*70}")
    rapid = run_rapid(frames)
    rh = sum(1 for r in rapid if r["hit"])
    rt = [r["elapsed"] for r in rapid]
    print(f"  → 命中: {rh}/{n} ({rh/n*100:.1f}%), 平均: {np.mean(rt):.3f}s")

    # ── 3. GLM-OCR ──
    print(f"\n{'─'*70}")
    print(f"  [2/2] GLM-OCR (全帧+ROI 原尺寸, FP16 GPU + torch.compile)")
    print(f"{'─'*70}")
    glm = run_glm_roi(frames)
    gh = sum(1 for r in glm if r["hit"])
    gt = [r["elapsed"] for r in glm]
    print(f"  → 命中: {gh}/{n} ({gh/n*100:.1f}%), 平均: {np.mean(gt):.3f}s")

    # ── 4. 汇总 ──
    both_hit = both_miss = r_only = g_only = 0
    for i in range(n):
        if rapid[i]["hit"] and glm[i]["hit"]:
            both_hit += 1
        elif rapid[i]["hit"]:
            r_only += 1
        elif glm[i]["hit"]:
            g_only += 1
        else:
            both_miss += 1

    print(f"\n{'='*70}")
    print(f"  汇总 ({n} 个样本)")
    print(f"{'='*70}")
    print(f"  {'指标':<18} {'RapidOCR':>14} {'GLM-OCR+ROI':>14}")
    print(f"  {'─'*48}")
    print(f"  {'命中率':<18} {rh}/{n} ({rh/n*100:.1f}%){'':>4} {gh}/{n} ({gh/n*100:.1f}%)")
    print(f"  {'平均耗时':<18} {np.mean(rt):.3f}s{'':>10} {np.mean(gt):.3f}s")
    print(f"  {'最快':<18} {min(rt):.3f}s{'':>10} {min(gt):.3f}s")
    print(f"  {'最慢':<18} {max(rt):.3f}s{'':>10} {max(gt):.3f}s")
    print(f"\n  双命中: {both_hit} | Rapid独占: {r_only} | GLM独占: {g_only} | 双未命中: {both_miss}")

    report = {"samples": n,
              "rapid": {"hits": rh, "rate": round(rh/n*100, 1), "avg": round(float(np.mean(rt)), 4)},
              "glm": {"hits": gh, "rate": round(gh/n*100, 1), "avg": round(float(np.mean(gt)), 4)},
              "overlap": {"both": both_hit, "rapid_only": r_only, "glm_only": g_only, "both_miss": both_miss}}
    out = os.path.join(PROJ_ROOT, "reports", f"ocr_compare_{n}_samples.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  报告: {out}")


if __name__ == "__main__":
    main()
