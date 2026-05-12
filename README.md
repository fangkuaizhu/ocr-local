# ocr-local

> 本地 OCR 文字提取工具 · GPU 加速 · 图片 + PDF · 专为 AI Agent 设计

**GitHub**: [https://github.com/fangkuaizhu/ocr-local](https://github.com/fangkuaizhu/ocr-local)

## 特性

- **纯本地运行** — 不调用任何外部 API，数据不出本机
- **GPU 加速** — 支持 NVIDIA GPU（PP-OCRv5_server 模型）
- **中英文混合识别** — 默认 `ch` 模式覆盖中英场景
- **输出结构化** — JSON 格式包含文字、置信度、坐标框
- **PDF 支持** — 自动逐页渲染 + OCR
- **Agent 友好** — CLI 调用，统一 JSON 输出，非零 exit code

## 环境要求

- **Python** 3.10 ~ 3.12（PaddlePaddle 不支持 3.14）
- **NVIDIA GPU**（推荐 8GB+ 显存，RTX 30/40/50 系列均可）
- **驱动** CUDA 12.x+（PaddlePaddle 自带 CUDA 库，无需单独装 CUDA Toolkit）
- **操作系统** Windows 10/11 64bit

> ⚠ **路径不能包含中文字符**。PaddlePaddle C++ 层的 `IsFileExists` 不处理 UTF-8 编码的中文路径，项目目录必须是纯英文。

## 快速开始

### 1. 克隆项目

```bash
# 路径不能含中文字符！PaddlePaddle C++ 层不处理 UTF-8 路径
git clone https://github.com/fangkuaizhu/ocr-local.git
cd ocr-local
```

### 2. 创建虚拟环境

```bash
# 需要 Python 3.10 ~ 3.12，推荐 3.12
python -m venv ocr_env
```

### 3. 安装依赖

```bash
# Git Bash / MSYS2
source ocr_env/Scripts/activate
# 或 CMD: ocr_env\Scripts\activate

# 先安装 PaddlePaddle GPU（根据你的 CUDA 驱动版本选一个）
# CUDA 12.9:
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/
# CUDA 13.0:
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu130/

# 再装 OCR 组件
pip install paddleocr paddlex
```

### 4. 验证安装

```bash
python ocr_cli.py --check
```

首次运行自动下载 OCR 模型（~210MB），存于 `paddle_cache/`。

### 5. 使用

```bash
# 图片 OCR
python ocr_cli.py --image screenshot.png --lang ch --format text

# PDF OCR -> 输出 JSON 到文件
python ocr_cli.py --image doc.pdf --lang ch --format json > result.json

# 低 DPI 更快，高 DPI 更精准
python ocr_cli.py --image doc.pdf --dpi 150 --format text

# JSON 格式（含坐标框）
python ocr_cli.py --image photo.jpg --lang ch --format json
```

## 输出格式

### JSON（默认）

```json
[
  {
    "text": "识别出的文字",
    "confidence": 0.9956,
    "box": [[48, 14], [187, 14], [187, 38], [48, 38]]
  }
]
```

### PDF 输出（json 格式）

```json
[
  {
    "page": 1,
    "blocks": [ ... ],
    "text": "第一页全文..."
  }
]
```

## CLI 参数

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `--image` | `-i` | 图片或 PDF 路径（必填） | — |
| `--lang` | `-l` | 语言：`ch` / `en` / `multi` | `ch` |
| `--format` | `-f` | 输出格式：`json` / `text` / `markdown` | `json` |
| `--dpi` | — | PDF 渲染 DPI | `200` |
| `--check` | — | 仅检查环境，不执行 OCR | — |

## 返回值

| 值 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 参数错误 |
| 2 | 文件不存在或无法读取 |
| 3 | 依赖缺失（缺少 Python 包） |
| 4 | OCR 内部错误 |

## 项目结构

```
ocr-local/
├── ocr_env/                # Python 虚拟环境（需自行创建）
├── paddle_cache/           # 模型缓存（自动下载）
│   └── official_models/    # PP-OCRv5 各子模型
├── test/                   # 测试图片
├── output/                 # 输出目录
├── ocr_core.py             # OCR 核心封装
├── ocr_cli.py              # CLI 入口
├── requirements.txt        # 依赖列表
└── README.md
```

## Python API

```python
import sys
sys.path.insert(0, "/path/to/ocr-local")

from ocr_core import extract_text, blocks_to_text, extract_text_from_pdf

# 图片 OCR
blocks = extract_text("screenshot.png", lang="ch")
print(blocks_to_text(blocks))

# PDF OCR
pages = extract_text_from_pdf("doc.pdf", lang="ch", dpi=200)
for p in pages:
    print(f"--- Page {p['page']} ---")
    print(p["text"])
```

## Agent 集成指南

本工具设计目的就是让 AI Agent（或其他自动化程序）能方便地调用本地 OCR。以下是一个标准集成流程。

### 环境准备（一次性的）

```bash
# 1. 克隆到纯英文路径
cd D:/tools/
git clone https://github.com/fangkuaizhu/ocr-local.git
cd ocr-local

# 2. 创建并激活虚拟环境
python -m venv ocr_env
source ocr_env/Scripts/activate   # Git Bash 或 MSYS2
# 或 CMD: ocr_env\Scripts\activate

# 3. 安装依赖
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/
pip install paddleocr paddlex

# 4. 验证
python ocr_cli.py --check

# 出现以下输出即环境正常：
# [ocr] PaddlePaddle 3.3.0
# [ocr] CUDA 可用: True
# [ocr] GPU 数量: 1
# [ocr] GPU 型号: NVIDIA GeForce RTX 5070 Ti ...
```

### 从 Agent Skill 中调用

在 Agent 的 SKILL.md 中写入以下指令，Agent 就能自动调用 OCR：

```markdown
图片/PDF 文字提取能力：

1. 项目路径：`<path>/ocr-local/`
2. 每次调用前激活 venv：`source <path>/ocr-local/ocr_env/Scripts/activate`
3. 使用 CLI：
   - `python ocr_cli.py --image <图片路径> --lang ch --format json`
   - `python ocr_cli.py --image <PDF路径> --lang ch --format json --dpi 150`
4. 输出是 JSON，可直接解析
```

### CLI 返回值语义（Agent 判断用）

| Exit Code | 含义 | Agent 行为 |
|-----------|------|-----------|
| 0 | 成功 | 解析 stdout JSON |
| 1 | 参数错误 | 检查命令格式 |
| 2 | 文件不存在 | 检查路径 |
| 3 | 依赖缺失 | 重新安装 pip 依赖 |
| 4 | OCR 内部错误 | 检查显存 / 模型缓存 |

## 常见问题

### Q: 报错 `Cannot open file inference.json`

项目路径包含中文字符。把项目移到纯英文路径下。

### Q: 首次运行很慢

首次会下载 OCR 模型（~210MB）。后续使用加载缓存，秒级启动。

### Q: 显存不够

- 关闭其他占用 GPU 的程序
- 降低 PDF 渲染 DPI（`--dpi 150`）
- 可换用 PP-OCRv4_mobile 模型（需手动指定模型目录）

### Q: 输出中文乱码

当前终端可能不支持 UTF-8 显示。保存到文件后用文本编辑器查看：
```bash
python ocr_cli.py --image test.png --lang ch --format text > result.txt
```
