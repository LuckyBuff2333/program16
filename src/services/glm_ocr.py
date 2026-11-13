"""GLM-OCR 本地时间区域 OCR（CPU，懒加载，线程安全）。

时间批量提取/功能测试/问题排查统一优先调用；模型不可用时由调用方回退 RapidOCR。
"""
from __future__ import annotations

import os
import threading

import cv2
import numpy as np

_LOCK = threading.Semaphore(2)  # 允许 2 路并行推理
_LOAD_LOCK = threading.Lock()    # 模型加载互斥，防止重复加载
_MODEL = None
_PROCESSOR = None
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "models", "GLM-OCR")


def model_path() -> str:
    """每台机器可不同：环境变量 > config.yaml ocr.glm_model_path > 默认 models/GLM-OCR。"""
    try:
        from src.config import load_config
        p = os.environ.get("GLM_OCR_MODEL_PATH") or load_config().get("ocr", {}).get("glm_model_path") or _DEFAULT_MODEL_PATH
    except Exception:
        p = os.environ.get("GLM_OCR_MODEL_PATH") or _DEFAULT_MODEL_PATH
    return p if os.path.isabs(p) else os.path.join(_PROJECT_ROOT, p)


def available() -> bool:
    p = model_path()
    return os.path.isdir(p) and os.path.isfile(os.path.join(p, "model.safetensors"))


def _load():
    global _MODEL, _PROCESSOR
    if _MODEL is not None:
        return
    with _LOAD_LOCK:
        if _MODEL is not None:
            return
        import torch
        from transformers import AutoProcessor, GlmOcrForConditionalGeneration
        _PROCESSOR = AutoProcessor.from_pretrained(model_path(), trust_remote_code=True)
        _MODEL = GlmOcrForConditionalGeneration.from_pretrained(
            model_path(), torch_dtype=torch.float32, device_map="cpu",
            trust_remote_code=True).eval()


def ocr_text(image_bgr: np.ndarray, max_new_tokens: int = 64) -> str:
    """识别一帧/一个时间 ROI 的文字；失败返回空串。"""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0 or not available():
        return ""
    try:
        import torch
        from PIL import Image
        with _LOCK:
            _load()
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb).convert("RGB")
            messages = [{"role": "user", "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "Text Recognition:"},
            ]}]
            inputs = _PROCESSOR.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors="pt").to(_MODEL.device)
            with torch.inference_mode():
                out = _MODEL.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            gen = out[:, inputs["input_ids"].shape[1]:]
            return _PROCESSOR.batch_decode(gen, skip_special_tokens=True)[0].strip()
    except Exception:
        return ""
