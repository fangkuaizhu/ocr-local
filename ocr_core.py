"""
ocr_core.py — PaddleOCR 核心封装

提供统一的 OCR 文字提取接口，供 CLI 和 Agent 调用。
输出统一为 JSON 格式，包含文字内容、置信度和坐标。
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# 确保 stdout/stderr 使用 UTF-8（避免输出 Unicode 字符时报 GBK 错误）
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 模型下载路径（当前项目目录下的 paddle_cache）
# 必须在 import paddle/paddlex 之前设置
# ---------------------------------------------------------------------------
_MODEL_CACHE = str(Path(__file__).parent / "paddle_cache")
Path(_MODEL_CACHE).mkdir(parents=True, exist_ok=True)

os.environ.setdefault("PADDLE_HOME", _MODEL_CACHE)
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", _MODEL_CACHE)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ---------------------------------------------------------------------------
# CUDA DLL 搜索路径：扫描虚拟环境中所有 nvidia 包的 bin 目录
# ---------------------------------------------------------------------------
_NVIDIA_BASE = Path(__file__).parent / "ocr_env" / "Lib" / "site-packages" / "nvidia"
if _NVIDIA_BASE.is_dir():
    for _pkg_dir in _NVIDIA_BASE.iterdir():
        _cuda_bin = _pkg_dir / "bin" / "x86_64"
        if _cuda_bin.is_dir():
            os.environ["PATH"] = str(_cuda_bin) + os.pathsep + os.environ.get("PATH", "")

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------
_REQUIRED_PACKAGES = {
    "paddlepaddle-gpu": "paddle",
    "paddleocr": "paddleocr",
    "paddlex": "paddlex",
    "numpy": "numpy",
    "pillow": "PIL",
}


def check_dependencies() -> list:
    """
    检查所有必需依赖是否可导入。

    返回
    ----
    list[str]
        缺失的包名列表。空列表表示全部就绪。
    """
    missing = []
    for pkg_name, import_name in _REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg_name)

    # 额外检查：PDF 支持需要 pypdfium2（PaddleX 自带，单独确认）
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        missing.append("pypdfium2")

    return missing


def print_diagnosis():
    """打印环境诊断信息：依赖、Paddle 版本、CUDA、GPU。"""
    missing = check_dependencies()
    if missing:
        print(f"[ocr] 缺少依赖: {', '.join(missing)}", file=sys.stderr)
        print(f"[ocr] 请运行: pip install {' '.join(missing)}", file=sys.stderr)
        return

    import paddle

    print(f"[ocr] PaddlePaddle {paddle.__version__}", file=sys.stderr)
    print(f"[ocr] CUDA 可用: {paddle.is_compiled_with_cuda()}", file=sys.stderr)
    if paddle.is_compiled_with_cuda():
        n = paddle.device.cuda.device_count()
        print(f"[ocr] GPU 数量: {n}", file=sys.stderr)
        if n > 0:
            print(f"[ocr] GPU 型号: {paddle.device.cuda.get_device_name(0)}", file=sys.stderr)
    print(f"[ocr] 模型缓存: {_MODEL_CACHE}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 边界框工具函数
# ---------------------------------------------------------------------------
def _to_box_list(box_data):
    """将各种格式的边界框统一转为 [[x,y], ...] 格式。"""
    if box_data is None:
        return []
    if isinstance(box_data, np.ndarray):
        box_data = box_data.tolist()
    # rec_boxes: [x1,y1,x2,y2]
    if len(box_data) == 4:
        return [[box_data[0], box_data[1]],
                [box_data[2], box_data[1]],
                [box_data[2], box_data[3]],
                [box_data[0], box_data[3]]]
    # rec_boxes full format: [x1,y1,x2,y2,x3,y3,x4,y4]
    if len(box_data) == 8:
        return [[box_data[0], box_data[1]],
                [box_data[2], box_data[3]],
                [box_data[4], box_data[5]],
                [box_data[6], box_data[7]]]
    # dt_polys: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    if all(isinstance(p, list) for p in box_data):
        return [[int(x), int(y)] for x, y in box_data]
    return []


# ---------------------------------------------------------------------------
# OCR 引擎（延迟初始化单例）
# ---------------------------------------------------------------------------
_ocr_instance = None
_ocr_lang = None


def _get_ocr(lang: str = "ch"):
    """获取或初始化 PaddleOCR 引擎（单例，按语言缓存）。"""
    global _ocr_instance, _ocr_lang

    if _ocr_instance is not None and _ocr_lang == lang:
        return _ocr_instance

    from paddleocr import PaddleOCR

    print(f"[ocr_core] 正在加载 PaddleOCR 引擎（lang={lang}），首次加载将下载模型...",
          file=sys.stderr)

    _ocr_instance = PaddleOCR(lang=lang)
    _ocr_lang = lang
    return _ocr_instance


# ---------------------------------------------------------------------------
# 核心 OCR 接口
# ---------------------------------------------------------------------------
def extract_text(image_path: str, lang: str = "ch") -> list:
    """
    对单张图片执行 OCR 文字提取。

    参数
    ----
    image_path : str
        图片文件路径（支持 jpg/png/bmp/tif 等常见格式）
    lang : str
        语言：'ch'（中英文混合）, 'en'（仅英文）, 'multi'（多语言）
        默认 'ch' 已覆盖中英文场景

    返回
    ----
    list[dict]
        每项包含：
            - text       : str   识别出的文字
            - confidence : float 置信度 (0~1)
            - box        : list  四边坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    """
    ocr = _get_ocr(lang)
    results = ocr.ocr(str(image_path))

    if not results:
        return []

    res = results[0]
    texts = res.get("rec_texts", [])
    scores = res.get("rec_scores", [])
    dt_polys = res.get("dt_polys", [])
    rec_boxes = res.get("rec_boxes", None)

    records = []
    for i, text in enumerate(texts):
        text = text.strip()
        if not text:
            continue
        conf = scores[i] if i < len(scores) else 0.0
        raw_box = None
        if rec_boxes is not None and i < len(rec_boxes):
            raw_box = rec_boxes[i]
        elif i < len(dt_polys):
            raw_box = dt_polys[i]
        records.append({
            "text": text,
            "confidence": round(float(conf), 4),
            "box": _to_box_list(raw_box),
        })

    # 按阅读顺序排序：从上到下，从左到右
    records.sort(key=lambda r: (r["box"][0][1] if r["box"] else 0,
                                r["box"][0][0] if r["box"] else 0))
    return records


def blocks_to_text(blocks: list) -> str:
    """将 OCR 结果拼接为纯文本（每行一条）。"""
    return "\n".join(b["text"] for b in blocks)


def blocks_to_markdown(blocks: list, line_gap: int = 20, indent_thresh: int = 30) -> str:
    """
    将 OCR 结果拼接为近似 Markdown。

    参数
    ----
    blocks : list
        extract_text 的返回结果
    line_gap : int
        多大纵向间距算段落分隔（像素，默认 20）
    indent_thresh : int
        多大横向偏移算缩进（像素，默认 30）
    """
    if not blocks:
        return ""

    lines = []
    prev_y = None
    prev_x = None

    for b in blocks:
        text = b["text"]
        box = b["box"]
        cur_y = box[0][1] if box else 0
        cur_x = box[0][0] if box else 0

        if prev_y is not None and (cur_y - prev_y) > line_gap:
            lines.append("")

        indent = "  " if prev_x is not None and (cur_x - prev_x) > indent_thresh else ""

        lines.append(f"{indent}{text}")
        prev_y = cur_y
        prev_x = cur_x

    return "\n".join(lines)


def extract_text_simple(image_path: str, lang: str = "ch") -> str:
    """快捷接口：直接返回纯文本。"""
    blocks = extract_text(image_path, lang)
    return blocks_to_text(blocks)


# ---------------------------------------------------------------------------
# PDF 支持
# ---------------------------------------------------------------------------
def extract_text_from_pdf(pdf_path: str, lang: str = "ch", dpi: int = 200) -> list:
    """
    对 PDF 文件逐页执行 OCR 文字提取。

    参数
    ----
    pdf_path : str
        PDF 文件路径
    lang : str
        语言（同 extract_text）
    dpi : int
        渲染分辨率，默认 200

    返回
    ----
    list[dict]
        每页：
            - page   : int   页码（从 1 开始）
            - blocks : list  该页 OCR 结果
            - text   : str   该页纯文本
    """
    import pypdfium2 as pdfium
    from PIL import Image

    pdf = pdfium.PdfDocument(pdf_path)
    pages_result = []

    try:
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            bitmap = page.render(scale=dpi / 72.0)
            pil_image = bitmap.to_pil()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
                pil_image.save(tmp_path, format="PNG")

            try:
                blocks = extract_text(tmp_path, lang=lang)
            finally:
                os.unlink(tmp_path)

            pages_result.append({
                "page": page_idx + 1,
                "blocks": blocks,
                "text": blocks_to_text(blocks),
            })
    finally:
        pdf.close()

    return pages_result


# ---------------------------------------------------------------------------
# 快速诊断
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print_diagnosis()
