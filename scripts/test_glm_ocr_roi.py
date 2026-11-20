"""
GLM-OCR ROI 裁剪对比测试：
同一批帧 → 全帧 vs ROI裁剪 → 看命中率变化
"""
import os, sys, time, json, re
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


def get_roi_crops(frame, enlarge=1):
    """ROI 区域裁剪，可选放大"""
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


def load_frames():
    """加载缓存帧"""
    frames = []
    for fn in sorted(f for f in os.listdir(CACHE_DIR) if f.endswith(".npy"))[:MAX_SAMPLES]:
        frames.append((fn.replace(".npy", ""), np.load(os.path.join(CACHE_DIR, fn))))
    return frames


def run_glm_mode(ocr_text, frames, label, use_roi=False, enlarge=1):
    """跑 GLM-OCR：全帧 or ROI"""
    import torch
    results = []
    total_t = 0.0
    for jira, img in frames:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()

        all_times = []
        if use_roi:
            # 先全帧，再 ROI 补充
            text = ocr_text(img, max_new_tokens=64)
            all_times.extend(TIME_RE.findall(text) if text else [])
            if not all_times:
                # 全帧未命中，尝试 ROI 区域
                for rname, crop in get_roi_crops(img, enlarge=enlarge):
                    text = ocr_text(crop, max_new_tokens=32)
                    found = TIME_RE.findall(text) if text else []
                    all_times.extend(found)
                    if found:
                        break
        else:
            text = ocr_text(img, max_new_tokens=64)
            all_times.extend(TIME_RE.findall(text) if text else [])

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        total_t += elapsed

        hit = len(all_times) > 0
        results.append({"jira": jira, "hit": hit, "times": all_times[:5],
                         "text": (text or "")[:120], "elapsed": round(elapsed, 4)})

    hits = sum(1 for r in results if r["hit"])
    times = [r["elapsed"] for r in results]
    print(f"  {label}: {hits}/{len(frames)} ({hits/len(frames)*100:.1f}%), 平均 {np.mean(times):.3f}s")
    return results, hits, times


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import torch

    print(f"{'='*70}")
    print(f"  GLM-OCR ROI 裁剪效果对比")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    print(f"{'='*70}")

    frames = load_frames()
    n = len(frames)
    print(f"缓存帧: {n}\n")

    from src.services.glm_ocr import ocr_text
    # 预热
    dummy = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
    ocr_text(dummy, max_new_tokens=8)
    print("  GLM-OCR 预热完成\n")

    # ── 方案1: 全帧 ──
    print(f"── [1/3] GLM-OCR 全帧 ──")
    r1, h1, t1 = run_glm_mode(ocr_text, frames, "全帧", use_roi=False)

    # ── 方案2: ROI 裁剪（不放大）──
    print(f"\n── [2/3] GLM-OCR 全帧+ROI裁剪（原尺寸）──")
    r2, h2, t2 = run_glm_mode(ocr_text, frames, "全帧+ROI", use_roi=True, enlarge=1)

    # ── 方案3: ROI 裁剪（2x放大）──
    print(f"\n── [3/3] GLM-OCR 全帧+ROI裁剪（2x放大）──")
    r3, h3, t3 = run_glm_mode(ocr_text, frames, "全帧+ROI 2x", use_roi=True, enlarge=2)

    # ── 逐帧对比 ──
    print(f"\n{'='*70}")
    print(f"  逐帧对比")
    print(f"{'='*70}")
    print(f"  {'JIRA':<16} {'全帧':>6} {'ROI':>6} {'ROI2x':>6}  {'全帧':>6} {'ROI':>6} {'ROI2x':>6}")
    print(f"  {'':16} {'命中':>6} {'命中':>6} {'命中':>6}  {'时间':>6} {'时间':>6} {'时间':>6}")
    print(f"  {'─'*64}")
    for i in range(n):
        marks = []
        ts = []
        for r in [r1, r2, r3]:
            marks.append("✓" if r[i]["hit"] else "✗")
            ts.append(f"{r[i]['elapsed']:.2f}s")
        print(f"  {r1[i]['jira']:<16} {marks[0]:>6} {marks[1]:>6} {marks[2]:>6}  {ts[0]:>6} {ts[1]:>6} {ts[2]:>6}")

    # ── 汇总 ──
    print(f"\n{'='*70}")
    print(f"  汇总对比 ({n} 个样本)")
    print(f"{'='*70}")
    print(f"  {'方案':<24} {'命中':>8} {'命中率':>8} {'平均':>8} {'最快':>8} {'最慢':>8}")
    print(f"  {'─'*66}")
    for label, hits, times in [
        ("全帧", h1, t1), ("全帧+ROI", h2, t2), ("全帧+ROI 2x", h3, t3)]:
        print(f"  {label:<24} {hits}/{n:>3} {hits/n*100:>6.1f}% {np.mean(times):>7.3f}s {min(times):>7.3f}s {max(times):>7.3f}s")

    # 保存
    report = {"samples": n, "modes": {}}
    for label, results, hits, times in [
        ("full", r1, h1, t1), ("roi_1x", r2, h2, t2), ("roi_2x", r3, h3, t3)]:
        report["modes"][label] = {"hits": hits, "hit_rate": round(hits/n*100, 1),
                                   "avg_time": round(float(np.mean(times)), 4), "details": results}
    out = os.path.join(PROJ_ROOT, "reports", "glm_ocr_roi_compare.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告: {out}")


if __name__ == "__main__":
    main()
