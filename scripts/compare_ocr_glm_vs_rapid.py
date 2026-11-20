"""
GLM-OCR vs RapidOCR 公平对比测试：
同一批缓存帧 → 两引擎分别识别 → 对比命中率和速度
"""
import os, sys, time, json, re, tempfile
import numpy as np
import cv2

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

MAX_SAMPLES = 20
CACHE_DIR = os.path.join(PROJ_ROOT, "_verify_tmp", "rapid_test_cache")
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


def get_roi_crops(frame):
    """ROI 区域裁剪 + 3x 放大 + CLAHE"""
    h, w = frame.shape[:2]
    crops = []
    for name, rx1, ry1, rx2, ry2 in ROI_REGIONS:
        x1, y1, x2, y2 = int(w*rx1), int(h*ry1), int(w*rx2), int(h*ry2)
        if x2-x1 < 40 or y2-y1 < 12:
            continue
        raw = frame[y1:y2, x1:x2]
        ch, cw = raw.shape[:2]
        enlarged = cv2.resize(raw, (int(cw*3), int(ch*3)), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        sharp = cv2.addWeighted(gray, 1.6, cv2.GaussianBlur(gray, (0, 0), 3), -0.6, 0)
        crops.append((name, cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)))
    return crops


def load_frames():
    """加载所有缓存帧"""
    frames = []
    npy_files = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith(".npy"))
    for fn in npy_files[:MAX_SAMPLES]:
        jira = fn.replace(".npy", "")
        img = np.load(os.path.join(CACHE_DIR, fn))
        frames.append((jira, img))
    return frames


def run_rapid(frames):
    """RapidOCR PP-OCRv5 GPU 识别"""
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
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rapid_compare.yaml")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)

    engine = RapidOCR(config_path=tmp_cfg)
    # 预热
    engine(np.random.randint(0, 255, (128, 256, 3), dtype=np.uint8))
    print("  RapidOCR 预热完成")

    results = []
    for jira, img in frames:
        crops = get_roi_crops(img)
        t0 = time.perf_counter()
        # 全帧 + ROI
        all_texts = []
        full_r = engine(img)
        if full_r and full_r[0]:
            all_texts.extend([str(e[1]) for e in full_r[0]])
        for rname, crop in crops:
            r = engine(crop)
            if r and r[0]:
                all_texts.extend([str(e[1]) for e in r[0]])
        elapsed = time.perf_counter() - t0

        found = []
        for t in all_texts:
            m = TIME_RE.search(t)
            if m:
                found.append(m.group(1))
        hit = len(found) > 0
        results.append({"jira": jira, "hit": hit, "times": found[:5],
                         "items": len(all_texts), "elapsed": round(elapsed, 4)})
    return results


def run_glm(frames):
    """GLM-OCR FP16 GPU 识别"""
    import torch
    from src.services.glm_ocr import ocr_text

    # 预热
    dummy = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
    ocr_text(dummy, max_new_tokens=8)
    print("  GLM-OCR 预热完成")

    results = []
    for jira, img in frames:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        text = ocr_text(img, max_new_tokens=64)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0

        found = TIME_RE.findall(text) if text else []
        hit = len(found) > 0
        results.append({"jira": jira, "hit": hit, "times": found[:5],
                         "text": (text or "")[:200], "elapsed": round(elapsed, 4)})
    return results


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import torch

    print(f"{'='*70}")
    print(f"  GLM-OCR vs RapidOCR 公平对比")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    print(f"{'='*70}")

    frames = load_frames()
    n = len(frames)
    print(f"\n缓存帧: {n} 个")
    if not frames:
        print("[ERROR] 无缓存帧")
        return

    # ── 1. RapidOCR ──
    print(f"\n{'─'*70}")
    print("  [1/2] RapidOCR PP-OCRv5 (全帧+ROI, GPU)")
    print(f"{'─'*70}")
    rapid = run_rapid(frames)

    rapid_hits = sum(1 for r in rapid if r["hit"])
    rapid_times = [r["elapsed"] for r in rapid]
    print(f"  命中率: {rapid_hits}/{n} ({rapid_hits/n*100:.1f}%)")
    print(f"  平均:   {np.mean(rapid_times):.3f}s")

    # ── 2. GLM-OCR ──
    print(f"\n{'─'*70}")
    print("  [2/2] GLM-OCR (全帧, FP16 GPU + torch.compile + SDPA)")
    print(f"{'─'*70}")
    glm = run_glm(frames)

    glm_hits = sum(1 for r in glm if r["hit"])
    glm_times = [r["elapsed"] for r in glm]
    print(f"  命中率: {glm_hits}/{n} ({glm_hits/n*100:.1f}%)")
    print(f"  平均:   {np.mean(glm_times):.3f}s")

    # ── 3. 逐帧对比 ──
    print(f"\n{'='*70}")
    print(f"  逐帧对比结果")
    print(f"{'='*70}")
    print(f"  {'JIRA':<16} {'RapidOCR':>10} {'GLM-OCR':>10} {'R时间':>7} {'G时间':>7}  {'状态'}")
    print(f"  {'─'*66}")

    both_hit, both_miss, r_only, g_only = 0, 0, 0, 0
    for i in range(n):
        r, g = rapid[i], glm[i]
        r_mark = "✓" if r["hit"] else "✗"
        g_mark = "✓" if g["hit"] else "✗"
        r_t = f"{r['elapsed']:.2f}s"
        g_t = f"{g['elapsed']:.2f}s"

        if r["hit"] and g["hit"]:
            status = "双命中"
            both_hit += 1
        elif r["hit"]:
            status = "Rapid独占"
            r_only += 1
        elif g["hit"]:
            status = "GLM独占"
            g_only += 1
        else:
            status = "双未命中"
            both_miss += 1

        print(f"  {r['jira']:<16} {r_mark:>10} {g_mark:>10} {r_t:>7} {g_t:>7}  {status}")

    # ── 4. 汇总 ──
    print(f"\n{'='*70}")
    print(f"  汇总对比 ({n} 个样本)")
    print(f"{'='*70}")
    print(f"  {'指标':<20} {'RapidOCR':>14} {'GLM-OCR':>14}")
    print(f"  {'─'*50}")
    print(f"  {'命中率':<20} {rapid_hits}/{n} ({rapid_hits/n*100:.1f}%){'':>4} {glm_hits}/{n} ({glm_hits/n*100:.1f}%)")
    print(f"  {'平均耗时':<20} {np.mean(rapid_times):.3f}s{'':>10} {np.mean(glm_times):.3f}s")
    print(f"  {'最快帧':<20} {min(rapid_times):.3f}s{'':>10} {min(glm_times):.3f}s")
    print(f"  {'最慢帧':<20} {max(rapid_times):.3f}s{'':>10} {max(glm_times):.3f}s")
    print(f"\n  双方命中: {both_hit}  |  Rapid独占: {r_only}  |  GLM独占: {g_only}  |  双未命中: {both_miss}")

    # 保存报告
    report = {
        "samples": n,
        "rapid_ocr": {"hits": rapid_hits, "hit_rate": round(rapid_hits/n*100, 1),
                       "avg_time": round(float(np.mean(rapid_times)), 4),
                       "details": rapid},
        "glm_ocr": {"hits": glm_hits, "hit_rate": round(glm_hits/n*100, 1),
                     "avg_time": round(float(np.mean(glm_times)), 4),
                     "details": glm},
        "overlap": {"both_hit": both_hit, "rapid_only": r_only,
                     "glm_only": g_only, "both_miss": both_miss},
    }
    out = os.path.join(PROJ_ROOT, "reports", "ocr_compare_glm_vs_rapid.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告: {out}")


if __name__ == "__main__":
    main()
