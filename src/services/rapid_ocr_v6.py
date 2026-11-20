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
_CPU_ENGINE = None
_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()  # DirectML session 非线程安全，串行推理
_USE_DML = os.environ.get("RAPID_OCR_USE_DML", "1") != "0"
logger = logging.getLogger("bug_doc_tool")


def model_dir() -> str:
    return _MODEL_DIR


def available() -> bool:
    return all(os.path.isfile(os.path.join(_MODEL_DIR, n)) for n in ("det.onnx", "rec.onnx", "dict.txt"))


def _get_engine(use_dml: bool = True):
    global _ENGINE, _CPU_ENGINE
    cached = _ENGINE if use_dml else _CPU_ENGINE
    if cached is not None:
        return cached
    with _LOCK:
        cached = _ENGINE if use_dml else _CPU_ENGINE
        if cached is not None:
            return cached
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
                "use_cuda": False, "use_dml": use_dml,
                "model_path": os.path.join(_MODEL_DIR, "det.onnx"),
                "limit_side_len": 736, "limit_type": "min",
                "std": [0.5, 0.5, 0.5], "mean": [0.5, 0.5, 0.5],
                "thresh": 0.2, "box_thresh": 0.45, "max_candidates": 3000,
                "unclip_ratio": 1.4, "use_dilation": True, "score_mode": "fast",
            },
            "Cls": {
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                "use_cuda": False, "use_dml": use_dml,
                "model_path": os.path.join(_PROJECT_ROOT, "models", "ppocrv5", "cls.onnx"),
                "cls_image_shape": [3, 80, 160], "cls_batch_num": 6,
                "cls_thresh": 0.9, "label_list": ["0", "180"],
            },
            "Rec": {
                "intra_op_num_threads": 1, "inter_op_num_threads": 1,
                "use_cuda": False, "use_dml": use_dml,
                "model_path": os.path.join(_MODEL_DIR, "rec.onnx"),
                "rec_img_shape": [3, 48, 320], "rec_batch_num": 6,
                "rec_keys_path": os.path.join(_MODEL_DIR, "dict.txt"),
            },
        }
        cp = os.path.join(tempfile.gettempdir(),
                          "rapidocr_v6_runtime.yaml" if use_dml else "rapidocr_v6_cpu_runtime.yaml")
        yaml.safe_dump(cfg, open(cp, "w", encoding="utf-8"), allow_unicode=True)
        eng = RapidOCR(config_path=cp)
        if use_dml:
            _ENGINE = eng
        else:
            _CPU_ENGINE = eng
        logger.info("RapidOCR v6 引擎初始化完成（%s）", "DirectML" if use_dml else "CPU 回退")
        return eng


def read_text(image_bgr, already_enhanced: bool = False) -> list:
    """返回 [[bbox, text, conf], ...]；不可用时返回空列表。"""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0 or not available():
        return []
    def _run(engine):
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

    with _INFER_LOCK:
        if _USE_DML:
            try:
                engine = _get_engine(use_dml=True)
                if engine is not None:
                    return _run(engine)
            except Exception as e:
                # ORT 在中文 Windows 下可能把底层错误信息按 GBK 解码，抛 UnicodeDecodeError；
                # 此时不要直接放弃，切 CPU 再试一次。
                logger.warning("RapidOCR v6 DirectML 推理异常，尝试 CPU 回退: %s", repr(e))
        # GPU 不可用/推理异常时回退 CPU；可用 RAPID_OCR_USE_DML=0 强制 CPU。
        try:
            cpu = _get_engine(use_dml=False)
            if cpu is not None:
                return _run(cpu)
        except Exception as e:
            logger.warning("RapidOCR v6 CPU 推理失败: %s", repr(e))
    return []
