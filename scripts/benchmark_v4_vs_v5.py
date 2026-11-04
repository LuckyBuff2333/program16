"""PP-OCRv4 vs PP-OCRv5 对比基准测试

使用项目现有图片 + 合成测试图，对比两个版本的 OCR 识别质量和置信度。
"""
import os, sys, time, cv2, numpy as np

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ─── V5 引擎（yaml 配置） ───
def _make_v5_engine():
    from rapidocr_onnxruntime import RapidOCR
    cfg = os.path.join(ROOT, "models", "ppocrv5", "rapidocr_v5.yaml")
    if os.path.exists(cfg):
        # 将 yaml 中的相对路径转为绝对路径
        import yaml
        with open(cfg) as f:
            ycfg = yaml.safe_load(f)
        for section in ["Det", "Cls", "Rec"]:
            if section in ycfg and "model_path" in ycfg[section]:
                mp = ycfg[section]["model_path"]
                if not os.path.isabs(mp):
                    ycfg[section]["model_path"] = os.path.join(ROOT, mp)
        # GPU 检测
        _gpu = False
        try:
            import shutil, subprocess
            if shutil.which("nvidia-smi"):
                r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                   capture_output=True, text=True, timeout=5)
                _gpu = r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            pass
        if _gpu:
            try:
                import onnxruntime as _ort
                _gpu = "CUDAExecutionProvider" in _ort.get_available_providers()
            except ImportError:
                _gpu = False
        if not _gpu:
            for section in ["Det", "Cls", "Rec"]:
                if section in ycfg:
                    ycfg[section]["use_cuda"] = False
        # 写入临时 yaml
        import tempfile
        tmp_cfg = os.path.join(tempfile.gettempdir(), "rapidocr_v5_bench.yaml")
        with open(tmp_cfg, "w") as f:
            yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)
        engine = RapidOCR(config_path=tmp_cfg)
        return engine, "PP-OCRv5" + ("+GPU" if _gpu else "+CPU")
    return RapidOCR(), "PP-OCRv5-fallback"

# ─── V4 引擎（默认配置） ───
def _make_v4_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(), "PP-OCRv4"

# ─── 合成测试图 ───
def _make_synthetic_images():
    """生成 6 张合成测试图，覆盖不同场景"""
    images = []

    # 1. 清晰中文 + 时间（模拟截屏）
    img = np.ones((200, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, "14:35:22", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 3)
    cv2.putText(img, "2026-11-04", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    images.append(("合成-清晰英文时间", img))

    # 2. 低对比度时间（模拟车机屏暗光）
    img = np.ones((200, 400, 3), dtype=np.uint8) * 40  # 暗背景
    cv2.putText(img, "19:18", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (80, 80, 80), 2)
    images.append(("合成-低对比度时间", img))

    # 3. 模糊时间（模拟手机拍屏运动模糊）
    img = np.ones((200, 400, 3), dtype=np.uint8) * 200
    cv2.putText(img, "16:42", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (50, 50, 50), 2)
    img = cv2.GaussianBlur(img, (15, 15), 5)
    images.append(("合成-模糊时间", img))

    # 4. 带噪声的时间（模拟视频压缩伪影）
    img = np.ones((150, 350, 3), dtype=np.uint8) * 180
    cv2.putText(img, "08:55", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 2)
    noise = np.random.randint(0, 60, img.shape, dtype=np.uint8)
    img = cv2.add(img, noise)
    images.append(("合成-噪声时间", img))

    # 5. 小字号时间（模拟远距离拍摄）
    img = np.ones((400, 800, 3), dtype=np.uint8) * 220
    cv2.putText(img, "10:30", (350, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1)
    images.append(("合成-小字号时间", img))

    # 6. 日期+时间完整格式
    img = np.ones((120, 500, 3), dtype=np.uint8) * 240
    cv2.putText(img, "2026-11-03 19:18:07", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    images.append(("合成-完整日期时间", img))

    return images


def _run_ocr(engine, image):
    """运行 OCR 并返回 [(text, conf, bbox)] + 耗时"""
    t0 = time.time()
    try:
        result, _ = engine(image)
    except Exception:
        result = None
    elapsed = time.time() - t0
    if not result:
        return [], elapsed
    items = []
    for r in result:
        bbox = r[0] if len(r) > 0 else []
        text = r[1] if len(r) > 1 else ""
        conf = r[2] if len(r) > 2 else 0.0
        items.append((text, conf, bbox))
    return items, elapsed


def main():
    print("=" * 80)
    print("PP-OCRv4 vs PP-OCRv5 对比基准测试")
    print("=" * 80)

    # 初始化引擎
    print("\n[初始化] PP-OCRv5 引擎...")
    v5_engine, v5_label = _make_v5_engine()
    print(f"  -> {v5_label}")

    print("[初始化] PP-OCRv4 引擎...")
    v4_engine, v4_label = _make_v4_engine()
    print(f"  -> {v4_label}")

    # 收集测试图片
    test_images = []

    # 现有图片
    existing = [
        ("vcu548720 原始帧", os.path.join(ROOT, "logs", "vcu548720_frame0.png")),
        ("vcu548720 ROI", os.path.join(ROOT, "logs", "vcu548720_roi.png")),
        ("vcu548720 ROI 3x", os.path.join(ROOT, "logs", "vcu548720_roi_3x.png")),
        ("vcu548720 CLAHE", os.path.join(ROOT, "logs", "vcu548720_roi_clahe.png")),
    ]
    for label, path in existing:
        if os.path.exists(path):
            img = cv2.imread(path)
            if img is not None:
                test_images.append((label, img))
                print(f"  [图片] {label}: {img.shape[1]}x{img.shape[0]}")

    # 合成测试图
    synth = _make_synthetic_images()
    test_images.extend(synth)
    for label, img in synth:
        print(f"  [合成] {label}: {img.shape[1]}x{img.shape[0]}")

    print(f"\n共 {len(test_images)} 张测试图\n")

    # 运行对比
    print(f"{'#':<3} {'测试图':<25} {'引擎':<15} {'文本数':>5} {'avg_conf':>9} {'耗时(ms)':>9} {'识别文本'}")
    print("-" * 120)

    v4_confs, v5_confs = [], []
    v4_times, v5_times = [], []

    for idx, (label, img) in enumerate(test_images, 1):
        for engine, elabel in [(v4_engine, v4_label), (v5_engine, v5_label)]:
            items, elapsed = _run_ocr(engine, img)
            texts = [t for t, c, b in items]
            confs = [c for t, c, b in items if c > 0]
            avg_conf = sum(confs) / len(confs) if confs else 0.0
            ms = elapsed * 1000

            if "v5" in elabel.lower() or "V5" in elabel:
                v5_confs.append(avg_conf)
                v5_times.append(ms)
            else:
                v4_confs.append(avg_conf)
                v4_times.append(ms)

            text_preview = " | ".join(texts)[:60]
            print(f"{idx:<3} {label:<25} {elabel:<15} {len(items):>5} {avg_conf:>9.3f} {ms:>9.0f} {text_preview}")

        print("-" * 120)

    # 汇总
    print("\n" + "=" * 80)
    print("汇总统计")
    print("=" * 80)
    n = len(test_images)
    print(f"{'指标':<20} {v4_label:<20} {v5_label:<20} {'差异':>10}")
    print("-" * 70)
    v4_avg_c = sum(v4_confs) / n if n else 0
    v5_avg_c = sum(v5_confs) / n if n else 0
    v4_avg_t = sum(v4_times) / n if n else 0
    v5_avg_t = sum(v5_times) / n if n else 0
    print(f"{'平均置信度':<20} {v4_avg_c:<20.4f} {v5_avg_c:<20.4f} {v5_avg_c - v4_avg_c:>+10.4f}")
    print(f"{'平均耗时(ms)':<20} {v4_avg_t:<20.0f} {v5_avg_t:<20.0f} {v5_avg_t - v4_avg_t:>+10.0f}")

    # 逐图置信度对比
    v4_wins = sum(1 for a, b in zip(v4_confs, v5_confs) if a > b)
    v5_wins = sum(1 for a, b in zip(v4_confs, v5_confs) if b > a)
    ties = n - v4_wins - v5_wins
    print(f"\n置信度胜出: {v4_label} {v4_wins}次, {v5_label} {v5_wins}次, 平局 {ties}次")


if __name__ == "__main__":
    main()
