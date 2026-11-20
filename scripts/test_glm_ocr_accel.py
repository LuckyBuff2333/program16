"""
GLM-OCR 加速方案测试：FP16 + torch.compile
对比：原始 FP16 vs torch.compile FP16 vs (可选) TensorRT
"""
import os, sys, time, json
import numpy as np
from PIL import Image

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

import torch
from transformers import AutoProcessor, GlmOcrForConditionalGeneration

MODEL_PATH = os.path.join(PROJ_ROOT, "models", "GLM-OCR")
TEST_IMG = os.path.join(PROJ_ROOT, "data", "troubleshoot", "VCU-556641_8c6e9b5d_frame_0001.jpg")

def load_model():
    """加载 FP16 模型"""
    print("加载 Processor...")
    processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
    print("加载模型 (FP16 + CUDA)...")
    model = GlmOcrForConditionalGeneration.from_pretrained(
        MODEL_PATH, torch_dtype=torch.float16, device_map="cuda",
        trust_remote_code=True
    ).eval()
    params = sum(p.numel() for p in model.parameters()) / 1e6
    mem = torch.cuda.memory_allocated() / 1024**3
    print(f"模型: {params:.0f}M 参数, 显存: {mem:.2f} GB")
    return processor, model


def run_inference(model, processor, image, label="推理", warmup=1, runs=5):
    """跑推理并计时"""
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text", "text": "请识别图片中的文字内容。"}
    ]}]

    # 预热
    for i in range(warmup):
        input_ids = processor.apply_chat_template(messages, add_generation_prompt=True,
                                                   tokenize=True, return_tensors="pt").to("cuda")
        with torch.no_grad():
            _ = model.generate(input_ids, max_new_tokens=256, do_sample=False)
        torch.cuda.synchronize()

    # 正式测试
    times = []
    results = []
    for i in range(runs):
        torch.cuda.synchronize()
        t0 = time.perf_counter()

        input_ids = processor.apply_chat_template(messages, add_generation_prompt=True,
                                                   tokenize=True, return_tensors="pt").to("cuda")
        prompt_len = input_ids.shape[-1]
        with torch.no_grad():
            output_ids = model.generate(input_ids, max_new_tokens=256, do_sample=False)
        torch.cuda.synchronize()

        elapsed = time.perf_counter() - t0
        times.append(elapsed)

        # 解码
        new_tokens = output_ids[0, prompt_len:]
        text = processor.decode(new_tokens, skip_special_tokens=True)
        results.append(text)
        print(f"  {label} #{i+1}: {elapsed:.3f}s → {text[:80]}...")

    avg = np.mean(times)
    print(f"  {label} 平均: {avg:.3f}s (min={min(times):.3f}, max={max(times):.3f})")
    return avg, results


def main():
    processor, model = load_model()

    # 加载测试图片
    if os.path.exists(TEST_IMG):
        image = Image.open(TEST_IMG).convert("RGB")
        print(f"测试图片: {TEST_IMG} ({image.size})")
    else:
        image = Image.fromarray(np.random.randint(0, 255, (540, 960, 3), dtype=np.uint8)).convert("RGB")
        print(f"使用随机图片 ({image.size})")

    print("\n===== 1. FP16 原始推理 =====")
    t_fp16, res_fp16 = run_inference(model, processor, image, "FP16原始", warmup=2, runs=5)

    print("\n===== 2. torch.compile + FP16 =====")
    print("编译模型中（首次约 1-3 分钟）...")
    t0 = time.perf_counter()
    model_compiled = torch.compile(model, mode="reduce-overhead", fullgraph=False)
    print(f"编译耗时: {time.perf_counter() - t0:.1f}s")

    t_compiled, res_compiled = run_inference(model_compiled, processor, image,
                                              "compiled", warmup=3, runs=5)

    # 对比
    speedup = t_fp16 / t_compiled
    print(f"\n===== 结果对比 =====")
    print(f"FP16 原始:       {t_fp16:.3f}s")
    print(f"torch.compile:   {t_compiled:.3f}s")
    print(f"加速比:          {speedup:.2f}x")
    print(f"结果一致:        {res_fp16[0] == res_compiled[0]}")

    # 保存结果
    report = {
        "model": "GLM-OCR",
        "gpu": torch.cuda.get_device_name(0),
        "fp16_time": round(t_fp16, 3),
        "compiled_time": round(t_compiled, 3),
        "speedup": round(speedup, 2),
        "result_match": res_fp16[0] == res_compiled[0],
        "fp16_result": res_fp16[0][:200],
        "compiled_result": res_compiled[0][:200],
    }
    report_path = os.path.join(PROJ_ROOT, "reports", "glm_ocr_accel_test.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
