"""
PaddleOCR vs RapidOCR 对比测试脚本
- 测试场景：不放大的原始图像识别
- 测试目标：时间类文本识别准确度
- 对比维度：识别准确率、置信度、耗时
"""
import os
import sys
import time
import tempfile
import shutil
import requests
import numpy as np
import cv2

# 项目根目录
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

# ── JIRA 配置 ──
JIRA_BASE = "https://jira-patac.apps.saic-gm.com"
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {JIRA_TOKEN}",
    "Accept": "application/json",
}

# ── 测试时间样本（模拟车载 HMI 常见时间格式）──
SAMPLES = [
    # (显示文本, 预期时间, 说明)
    ("11:33", "11:33", "简单数字时钟"),
    ("14:28:38", "14:28:38", "带秒时钟"),
    ("Oct 9  13:01", "13:01", "英文月份+时间"),
    ("2026-10-09 14:28", "2026-10-09 14:28", "完整日期时间"),
    ("13:03", "13:03", "下午时间"),
    ("09:15:22", "09:15:22", "上午带秒"),
]


def _make_hmi_image(text: str, width=1920, height=720) -> np.ndarray:
    """生成模拟车载 HMI 界面的测试图像（深色背景+浅色数字时钟）"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (35, 30, 25)
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_len = len(text)
    font_scale = 3.5 if text_len <= 8 else (2.5 if text_len <= 15 else 1.8)
    thickness = max(3, int(font_scale * 2))
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    x = (width - tw) // 2
    y = int(height * 0.35) + th // 2
    cv2.putText(img, text, (x, y), font, font_scale, (220, 220, 210), thickness, cv2.LINE_AA)
    # 顶部状态栏
    cv2.rectangle(img, (0, 0), (width, 40), (50, 45, 40), -1)
    cv2.putText(img, "565km", (50, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 170), 1)
    cv2.putText(img, "32%", (width - 100, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 170), 1)
    # 底部导航栏
    cv2.rectangle(img, (0, height - 80), (width, height), (45, 40, 35), -1)
    cv2.putText(img, "Auto Park", (width // 2 - 80, height - 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (160, 160, 150), 1)
    return img


def _make_hmi_chinese(text: str, width=1920, height=720) -> np.ndarray:
    """生成含中文的 HMI 测试图像"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return _make_hmi_image(text, width, height)
    pil_img = Image.new("RGB", (width, height), (25, 30, 35))
    draw = ImageDraw.Draw(pil_img)
    font_paths = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 120)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = int(height * 0.30)
    draw.text((x, y), text, fill=(220, 220, 210), font=font)
    draw.rectangle([(0, 0), (width, 40)], fill=(40, 45, 50))
    small_font = ImageFont.truetype(font_paths[0], 20) if os.path.exists(font_paths[0]) else font
    draw.text((50, 8), "565km 32%", fill=(180, 180, 170), font=small_font)
    draw.rectangle([(0, height - 80), (width, height)], fill=(35, 40, 45))
    nav_font = ImageFont.truetype(font_paths[0], 28) if os.path.exists(font_paths[0]) else font
    draw.text((width // 2 - 60, height - 55), "Auto Park", fill=(160, 160, 150), font=nav_font)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def init_rapid_ocr():
    """初始化 RapidOCR（使用项目配置，完整字典）"""
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
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rapidocr_test.yaml")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)
    engine = RapidOCR(config_path=tmp_cfg)
    print("[RapidOCR] 初始化完成（PP-OCRv5, CPU, 完整字典）")
    return engine


def init_paddle_ocr():
    """初始化 PaddleOCR（PaddleX 流水线，PP-OCRv6 medium，paddle_fp32 推理）"""
    from paddlex.inference import create_pipeline
    from paddlex.inference.models.runners.paddle_static.config.pp_option import PaddlePredictorOption
    # paddle_fp32 模式绕过 oneDNN/PIR bug
    pp = PaddlePredictorOption(run_mode='paddle_fp32')
    pipe = create_pipeline(pipeline='OCR', pp_option=pp)
    print("[PaddleOCR] 初始化完成（PaddleX PP-OCRv6 medium, paddle_fp32, CPU）")
    return pipe


def run_rapid(engine, img: np.ndarray) -> tuple:
    """RapidOCR 识别（不放大）"""
    t0 = time.perf_counter()
    result = engine(img)
    elapsed = time.perf_counter() - t0
    if not result or not result[0]:
        return [], elapsed
    items = []
    for entry in result[0]:
        items.append({"text": str(entry[1]), "conf": float(entry[2]), "box": entry[0]})
    return items, elapsed


def run_paddle(pipe, img: np.ndarray) -> tuple:
    """PaddleOCR PaddleX PP-OCRv6 推理（不放大）"""
    t0 = time.perf_counter()
    results = list(pipe.predict(img))
    elapsed = time.perf_counter() - t0
    items = []
    if results:
        r = results[0]
        texts = r.get('rec_texts', []) if hasattr(r, 'get') else getattr(r, 'rec_texts', [])
        scores = r.get('rec_scores', []) if hasattr(r, 'get') else getattr(r, 'rec_scores', [])
        polys = r.get('dt_polys', []) if hasattr(r, 'get') else getattr(r, 'dt_polys', [])
        for txt, conf, box in zip(texts, scores, polys):
            items.append({"text": str(txt), "conf": float(conf), "box": box})
    return items, elapsed


def download_jira_image(attachment_id: str, filename: str) -> str:
    """从 JIRA 下载附件图片"""
    url = f"{JIRA_BASE}/secure/attachment/{attachment_id}/{filename}"
    print(f"  下载 JIRA 附件: {filename} ...")
    resp = requests.get(url, headers=HEADERS, timeout=60, verify=False)
    if resp.status_code != 200:
        print(f"  下载失败: HTTP {resp.status_code}")
        return None
    safe_name = filename.replace("%", "_").replace("/", "_")
    tmp_path = os.path.join(tempfile.gettempdir(), f"ocr_test_{safe_name}")
    with open(tmp_path, "wb") as f:
        f.write(resp.content)
    print(f"  下载完成: {len(resp.content)} bytes -> {tmp_path}")
    return tmp_path


def compare_results(rapid_items, rapid_time, paddle_items, paddle_time, expected_time, image_desc):
    """对比两个引擎的识别结果"""
    import re
    time_re = re.compile(r'(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')

    print(f"\n{'='*80}")
    print(f"  测试图像: {image_desc}")
    print(f"  预期时间: {expected_time}")
    print(f"{'='*80}")

    # RapidOCR 结果
    print(f"\n  [RapidOCR] 耗时: {rapid_time:.3f}s  识别到 {len(rapid_items)} 条文本")
    rapid_time_hits = []
    for item in rapid_items:
        marker = ""
        m = time_re.search(item["text"])
        if m:
            marker = f"  ← 时间: {m.group(1)}"
            rapid_time_hits.append(m.group(1))
        print(f"    [{item['conf']:.3f}] {item['text']}{marker}")

    # PaddleOCR 结果
    print(f"\n  [PaddleOCR] 耗时: {paddle_time:.3f}s  识别到 {len(paddle_items)} 条文本")
    paddle_time_hits = []
    for item in paddle_items:
        marker = ""
        m = time_re.search(item["text"])
        if m:
            marker = f"  ← 时间: {m.group(1)}"
            paddle_time_hits.append(m.group(1))
        print(f"    [{item['conf']:.3f}] {item['text']}{marker}")

    # 准确度对比
    rapid_hit = any(expected_time in t for t in rapid_time_hits) if expected_time else False
    paddle_hit = any(expected_time in t for t in paddle_time_hits) if expected_time else False
    rapid_avg_conf = np.mean([i["conf"] for i in rapid_items]) if rapid_items else 0
    paddle_avg_conf = np.mean([i["conf"] for i in paddle_items]) if paddle_items else 0

    print(f"\n  ── 对比摘要 ──")
    print(f"  时间命中:  RapidOCR={'✓' if rapid_hit else '✗'}  |  PaddleOCR={'✓' if paddle_hit else '✗'}")
    print(f"  平均置信度: RapidOCR={rapid_avg_conf:.3f}  |  PaddleOCR={paddle_avg_conf:.3f}")
    print(f"  耗时:     RapidOCR={rapid_time:.3f}s  |  PaddleOCR={paddle_time:.3f}s")

    return {
        "image": image_desc,
        "expected": expected_time,
        "rapid_hit": rapid_hit,
        "paddle_hit": paddle_hit,
        "rapid_conf": rapid_avg_conf,
        "paddle_conf": paddle_avg_conf,
        "rapid_time": rapid_time,
        "paddle_time": paddle_time,
        "rapid_count": len(rapid_items),
        "paddle_count": len(paddle_items),
    }


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 先导入 torch 再导入 paddle，避免 DLL 冲突
    import torch
    print(f"torch: {torch.__version__}")

    print("=" * 80)
    print("  PaddleOCR vs RapidOCR 对比测试（不放大原始图像）")
    print("=" * 80)

    # 1. 初始化引擎
    print("\n── 初始化 OCR 引擎 ──")
    rapid_engine = init_rapid_ocr()
    paddle_ocr = init_paddle_ocr()

    results = []

    # 2. 合成测试图像
    print("\n── 合成 HMI 测试图像 ──")
    test_images = []
    for text, expected, desc in SAMPLES:
        img = _make_hmi_image(text)
        test_images.append((img, expected, f"合成-{desc}: {text}"))

    # 中文类测试
    cn_samples = [
        ("Mon 10:30", "10:30", "英文星期+时间"),
        ("星期三 16:45", "16:45", "中文星期+时间"),
        ("昨天 15:20", "15:20", "中文相对日期"),
    ]
    for text, expected, desc in cn_samples:
        img = _make_hmi_chinese(text)
        test_images.append((img, expected, f"合成-{desc}: {text}"))

    # 3. JIRA 真实附件测试
    print("\n── 下载 JIRA 真实附件 ──")
    jira_images = []
    try:
        path = download_jira_image("2872676", "UI%E5%9B%BE.png")
        if path and os.path.exists(path):
            img = cv2.imread(path)
            if img is not None:
                jira_images.append((img, None, "VCU-553841 UI图.png (真实附件)"))
                print(f"  图像尺寸: {img.shape[1]}x{img.shape[0]}")
    except Exception as e:
        print(f"  JIRA 附件下载失败: {e}")

    # 4. 执行对比测试
    print("\n── 开始对比测试 ──")
    all_images = test_images + jira_images

    for img, expected, desc in all_images:
        rapid_items, rapid_time = run_rapid(rapid_engine, img)
        paddle_items, paddle_time = run_paddle(paddle_ocr, img)
        r = compare_results(rapid_items, rapid_time, paddle_items, paddle_time, expected, desc)
        results.append(r)

    # 5. 汇总报告
    print(f"\n\n{'='*80}")
    print("  汇总报告")
    print(f"{'='*80}")
    header = f"{'测试图像':<40} {'Rapid命中':>10} {'Paddle命中':>10} {'Rapid置信':>10} {'Paddle置信':>10} {'Rapid耗时':>10} {'Paddle耗时':>10}"
    print(header)
    print("-" * 100)

    rapid_hits = 0
    paddle_hits = 0
    for r in results:
        rapid_hits += int(r["rapid_hit"])
        paddle_hits += int(r["paddle_hit"])
        img_name = r["image"][:38]
        print(f"{img_name:<40} {'✓' if r['rapid_hit'] else '✗':>10} {'✓' if r['paddle_hit'] else '✗':>10} "
              f"{r['rapid_conf']:>10.3f} {r['paddle_conf']:>10.3f} "
              f"{r['rapid_time']:>9.3f}s {r['paddle_time']:>9.3f}s")

    total_with_expected = sum(1 for r in results if r["expected"])
    print("-" * 100)
    print(f"时间命中率:  RapidOCR = {rapid_hits}/{total_with_expected} ({rapid_hits/max(total_with_expected,1)*100:.0f}%)  |  "
          f"PaddleOCR = {paddle_hits}/{total_with_expected} ({paddle_hits/max(total_with_expected,1)*100:.0f}%)")

    rapid_avg_time = np.mean([r["rapid_time"] for r in results])
    paddle_avg_time = np.mean([r["paddle_time"] for r in results])
    rapid_avg_conf_all = np.mean([r["rapid_conf"] for r in results if r["rapid_conf"] > 0])
    paddle_avg_conf_all = np.mean([r["paddle_conf"] for r in results if r["paddle_conf"] > 0])
    print(f"平均置信度:  RapidOCR = {rapid_avg_conf_all:.3f}  |  PaddleOCR = {paddle_avg_conf_all:.3f}")
    print(f"平均耗时:    RapidOCR = {rapid_avg_time:.3f}s  |  PaddleOCR = {paddle_avg_time:.3f}s")
    print(f"\n结论: ", end="")
    if paddle_hits > rapid_hits:
        print(f"PaddleOCR 在时间识别准确度上优于 RapidOCR（{paddle_hits} vs {rapid_hits}）")
    elif rapid_hits > paddle_hits:
        print(f"RapidOCR 在时间识别准确度上优于 PaddleOCR（{rapid_hits} vs {paddle_hits}）")
    else:
        print(f"两者时间识别准确度相当（均为 {rapid_hits} 命中）")


if __name__ == "__main__":
    main()
