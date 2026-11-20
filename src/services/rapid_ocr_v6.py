"""RapidOCR PP-OCRv6 ONNX 推理（DirectML 优先，CPU 回退）。

仅使用项目内 models/ppocrv6_medium_onnx 的 det/rec/dict。
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MODEL_DIR = os.path.join(_PROJECT_ROOT, "models", "ppocrv6_medium_onnx")
_ENGINE = None
_LOCK = threading.Lock()
logger = logging.getLogger("bug_doc_tool")


def model_dir() -> str:
    return _MODEL_DIR


def available() -> bool:
    return all(os.path.isfile(os.path.join(_MODEL_DIR, n)) for n in ("det.onnx", "rec.onnx", "dict.txt"))


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if not available():
            logger.warning("RapidOCR v6 模型不完整: %s", _MODEL_DIR)
            return None
        import yaml
        from rapidocr_onnxruntime import RapidOCR
        cfg = {
            "Global": {
                "text_score": 0.15, "use_det": True, "use_cls": False, "use_rec": True,
                "print_verbose": False, "min_height": 30, "width_height_ratio": 8,
                "max_side_len": 2000, "min_side_len": 30, "return_word_box": False,
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
            },
            "Det": {
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                "use_cuda": False, "use_dml": True,
                "model_path": os.path.join(_MODEL_DIR, "det.onnx"),
                "limit_side_len": 736, "limit_type": "min",
                "std": [0.5, 0.5, 0.5], "mean": [0.5, 0.5, 0.5],
                "thresh": 0.2, "box_thresh": 0.45, "max_candidates": 3000,
                "unclip_ratio": 1.4, "use_dilation": True, "score_mode": "fast",
            },
            "Cls": {
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                "use_cuda": False, "use_dml": True,
                "model_path": os.path.join(_PROJECT_ROOT, "models", "ppocrv5", "cls.onnx"),
                "cls_image_shape": [3, 80, 160], "cls_batch_num": 6,
                "cls_thresh": 0.9, "label_list": ["0", "180"],
            },
            "Rec": {
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                "use_cuda": False, "use_dml": True,
                "model_path": os.path.join(_MODEL_DIR, "rec.onnx"),
                "rec_img_shape": [3, 48, 320], "rec_batch_num": 6,
                "rec_keys_path": os.path.join(_MODEL_DIR, "dict.txt"),
            },
        }
        cp = os.path.join(tempfile.gettempdir(), "rapidocr_v6_runtime.yaml")
        yaml.safe_dump(cfg, open(cp, "w", encoding="utf-8"), allow_unicode=True)
        _ENGINE = RapidOCR(config_path=cp)
        logger.info("RapidOCR v6 引擎初始化完成（DirectML/CPU 自动）")
        return _ENGINE


def read_text(image_bgr, already_enhanced: bool = False) -> list:
    """返回 [[bbox, text, conf], ...]；不可用时返回空列表。"""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0 or not available():
        return []
    engine = _get_engine()
    if engine is None:
        return []
    try:
        result, _ = engine(image_bgr)
        out: list[Any] = []
        for item in result or []:
            if len(item) < 2:
                continue
            bbox = item[0]
            text = str(item[1])
            conf = float(item[2]) if len(item) > 2 else 0.0
            out.append([bbox, text, conf])
        return out
    except Exception as e:
        logger.warning("RapidOCR v6 推理异常: %s", e)
        return []
