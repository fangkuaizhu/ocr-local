#!/usr/bin/env python3
"""
ocr_cli.py — 本地 OCR 命令行工具

Agent 通过 bash 调用的统一入口。支持图片和 PDF 两种输入。

用法
----
  python ocr_cli.py --image screenshot.png
  python ocr_cli.py --image doc.jpg --lang en --format text
  python ocr_cli.py --image file.pdf --lang ch --format json > result.json

返回值
-------
  0  成功
  1  参数错误
  2  文件不存在或无法读取
  3  依赖缺失
  4  OCR 内部错误
"""

import argparse
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 确保 stdout/stderr 使用 UTF-8
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

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from ocr_core import (
    check_dependencies,
    extract_text,
    extract_text_from_pdf,
    blocks_to_text,
    blocks_to_markdown,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="本地 OCR 文字提取工具（支持图片和 PDF）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--image", "-i",
        help="图片或 PDF 路径（--check 模式下可选）",
    )
    parser.add_argument(
        "--lang", "-l",
        default="ch",
        choices=["ch", "en", "multi"],
        help="识别语言：ch=中英文混合（默认）, en=英文, multi=多语言",
    )
    parser.add_argument(
        "--format", "-f",
        default="json",
        choices=["json", "text", "markdown"],
        help="输出格式（默认 json）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="PDF 渲染 DPI（默认 200）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查依赖和环境，不执行 OCR",
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="提交到后台队列（非阻塞），需 --daemon 已在运行",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="启动 OCR 守护进程（模型常驻，轮询队列）",
    )
    parser.add_argument(
        "--queue-status",
        action="store_true",
        help="查看队列状态",
    )
    parser.add_argument(
        "--wait", "-w",
        type=int,
        default=0,
        metavar="SECS",
        help="enqueue 后等待结果的最大秒数",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    # ── 守护进程 ──
    if args.daemon:
        from queue_manager import OcrDaemon
        OcrDaemon().run()
        return 0

    # ── 队列状态 ──
    if args.queue_status:
        from queue_manager import queue_status
        print(json.dumps(queue_status(), ensure_ascii=False, indent=2))
        return 0

    # ── 提交到队列 ──
    if args.enqueue:
        if not args.image:
            print("错误：--enqueue 需配合 --image", file=sys.stderr)
            return 1
        from queue_manager import enqueue, get_job_result, queue_status
        path = Path(args.image)
        if not path.exists():
            print(f"错误：文件不存在 → {path}", file=sys.stderr)
            return 2
        job_id = enqueue(str(path), lang=args.lang)
        status = queue_status()
        print(f"OCR 任务已提交")
        print(f"任务ID: {job_id}")
        print(f"队列: pending={status['pending']}, running={status['running']}")
        if not status["daemon_alive"]:
            print("⚠ daemon 未运行，任务将等待")

        # 可选等待
        if args.wait > 0:
            waited = 0
            while waited < args.wait:
                result = get_job_result(job_id)
                if result:
                    if result["status"] == "done":
                        blocks = result["result"]
                        print(f"\n完成 ({len(blocks)} 行):")
                        for b in blocks:
                            print(f"  [{b['text']}] ({b['confidence']:.0%})")
                        return 0
                    else:
                        print(f"\n失败: {result['error']}", file=sys.stderr)
                        return 4
                time.sleep(2)
                waited += 2
            print(f"\n等待超时，任务仍在队列中。使用 --queue-status 查看。")
        return 0

    # ── 直接模式（原有逻辑）──

    # 依赖检查（check 模式和正常模式都需要）
    missing = check_dependencies()
    if missing:
        print(f"错误：缺少依赖: {', '.join(missing)}", file=sys.stderr)
        print(f"请运行: pip install {' '.join(missing)}", file=sys.stderr)
        return 3

    # 仅诊断模式
    if args.check:
        from ocr_core import print_diagnosis
        print_diagnosis()
        return 0

    # 路径校验
    if not args.image:
        print("错误：--image/-i 是必填参数", file=sys.stderr)
        return 1
    path = Path(args.image)
    if not path.exists():
        print(f"错误：文件不存在 → {path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"错误：路径不是文件 → {path}", file=sys.stderr)
        return 2

    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            pages = extract_text_from_pdf(str(path), lang=args.lang, dpi=args.dpi)
            if args.format == "json":
                print(json.dumps(pages, ensure_ascii=False, indent=2))
            elif args.format == "text":
                for p in pages:
                    print(f"--- 第 {p['page']} 页 ---")
                    print(p["text"])
            elif args.format == "markdown":
                for p in pages:
                    print(f"## 第 {p['page']} 页\n")
                    print(p["text"])
                    print()
        else:
            blocks = extract_text(str(path), lang=args.lang)
            if args.format == "json":
                print(json.dumps(blocks, ensure_ascii=False, indent=2))
            elif args.format == "text":
                print(blocks_to_text(blocks))
            elif args.format == "markdown":
                print(blocks_to_markdown(blocks))
    except Exception as e:
        print(f"OCR 错误：{e}", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
