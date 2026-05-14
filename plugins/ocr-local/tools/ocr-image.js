/**
 * ocr-image — 图片 OCR 文字提取
 *
 * 调用本地 PaddleOCR GPU 识别图片中的文字。
 * 输入：图片文件路径
 * 输出：格式化文字 + 置信度，含全文拼接
 */

import { execSync } from "child_process";
import { existsSync, copyFileSync, mkdirSync, writeFileSync, unlinkSync } from "fs";
import path from "path";

// ── 常量 ──────────────────────────────────────────────────────────────
const PROJECT_DIR = "H:/ocr-local";
const PYTHON = path.join(PROJECT_DIR, "ocr_env/Scripts/python.exe");
const CLI = path.join(PROJECT_DIR, "ocr_cli.py");
const TEMP_DIR = path.join(PROJECT_DIR, "temp");

// ── 参数 schema ──────────────────────────────────────────────────────

export const name = "ocr-image";
export const description =
  "对图片进行 OCR 文字识别提取，支持截图、照片、扫描件等。返回识别出的文字内容及每行的置信度。";

export const parameters = {
  type: "object",
  properties: {
    imagePath: {
      type: "string",
      description: "图片文件的完整路径，如 C:/Users/name/screenshot.png",
    },
    lang: {
      type: "string",
      enum: ["ch", "en", "multi"],
      description: "识别语言：ch=中英文混合, en=仅英文, multi=多语言",
    },
  },
  required: ["imagePath"],
};

// ── 路径处理 ─────────────────────────────────────────────────────────

function ensureSafePath(originalPath) {
  const hasChinese = /[\u4e00-\u9fff]/.test(originalPath);
  if (!hasChinese) return { path: originalPath, temporary: false };

  const ext = path.extname(originalPath);
  const safeName = `ocr_input_${Date.now()}${ext}`;
  mkdirSync(TEMP_DIR, { recursive: true });
  const dest = path.join(TEMP_DIR, safeName);
  copyFileSync(originalPath, dest);
  return { path: dest, temporary: true };
}

function tryCleanup(filePath) {
  if (filePath && filePath.startsWith(TEMP_DIR)) {
    try { unlinkSync(filePath); } catch { /* ok */ }
  }
}

// ── 执行 ─────────────────────────────────────────────────────────────

export async function execute({ imagePath, lang }, toolCtx) {
  // 1. 校验
  if (!imagePath) return "错误：未提供图片路径（imagePath）";
  if (!existsSync(imagePath)) return `错误：文件不存在 — ${imagePath}`;

  // 2. 路径去中文
  const { path: safeImgPath, temporary } = ensureSafePath(imagePath);

  try {
    // 3. 跑 CLI
    const langOpt = lang || "ch";
    const cmd = `"${PYTHON}" "${CLI}" --image "${safeImgPath}" --lang ${langOpt} --format json`;

    const stdout = execSync(cmd, {
      cwd: PROJECT_DIR,
      timeout: 30_000,
      encoding: "utf-8",
      maxBuffer: 10 * 1024 * 1024,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    }).trim();

    // 4. 解析
    let blocks;
    try {
      blocks = JSON.parse(stdout);
    } catch {
      return `OCR 输出解析失败。原始输出前 2000 字符：\n${stdout.slice(0, 2000)}`;
    }

    if (!Array.isArray(blocks) || blocks.length === 0) {
      return "未识别到任何文字（空结果）";
    }

    // 5. 格式化
    const lines = blocks.map((b, i) => {
      const conf = (b.confidence * 100).toFixed(1);
      return `${i + 1}. [${b.text}]  (${conf}%)`;
    });
    const fullText = blocks.map((b) => b.text).join("\n");

    const result = [
      `共识别 ${blocks.length} 行文字`,
      "",
      ...lines,
      "",
      "── 全文 ──",
      fullText,
    ].join("\n");

    // 6. 原始 JSON 落盘 + stageFile
    const jsonPath = path.join(TEMP_DIR, `ocr_raw_${Date.now()}.json`);
    writeFileSync(jsonPath, stdout, "utf-8");
    await toolCtx.stageFile({
      sessionPath: "ocr_result.json",
      filePath: jsonPath,
      label: "OCR 原始结果 (JSON)",
    });

    return result;
  } catch (err) {
    const msg = err.stderr || err.message || String(err);
    return `OCR 执行失败：\n${msg.slice(0, 2000)}`;
  } finally {
    if (temporary) tryCleanup(safeImgPath);
  }
}
