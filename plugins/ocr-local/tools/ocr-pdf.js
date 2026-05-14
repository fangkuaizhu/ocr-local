/**
 * ocr-pdf — PDF 文档 OCR 文字提取
 *
 * 调用本地 PaddleOCR GPU 逐页识别 PDF 中的文字。
 * 输入：PDF 文件路径
 * 输出：逐页文字 + 全文拼接
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

export const name = "ocr-pdf";
export const description =
  "对 PDF 文档逐页进行 OCR 文字识别提取。适用于扫描件、课后答案、电子书等。返回每页的文字内容。";

export const parameters = {
  type: "object",
  properties: {
    pdfPath: {
      type: "string",
      description: "PDF 文件的完整路径，如 C:/Users/name/document.pdf",
    },
    lang: {
      type: "string",
      enum: ["ch", "en", "multi"],
      description: "识别语言：ch=中英文混合, en=仅英文, multi=多语言",
    },
    dpi: {
      type: "number",
      description: "PDF 渲染 DPI，200 够用，300 更精细但慢 2x。默认 150",
    },
    format: {
      type: "string",
      enum: ["json", "text", "markdown"],
      description: "输出格式：json=含坐标, text=纯文本, markdown=带标记",
    },
  },
  required: ["pdfPath"],
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

// ── 辅助 ─────────────────────────────────────────────────────────────

function blocksToText(blocks) {
  if (!Array.isArray(blocks)) return "";
  return blocks.map((b) => b.text || "").join("\n");
}

// ── 执行 ─────────────────────────────────────────────────────────────

export async function execute({ pdfPath, lang, dpi, format }, toolCtx) {
  // 1. 校验
  if (!pdfPath) return "错误：未提供 PDF 路径（pdfPath）";
  if (!existsSync(pdfPath)) return `错误：文件不存在 — ${pdfPath}`;

  // 2. 路径去中文
  const { path: safePdfPath, temporary } = ensureSafePath(pdfPath);

  try {
    // 3. 跑 CLI
    const langOpt = lang || "ch";
    const dpiOpt = dpi || 150;
    const fmtOpt = format || "text";
    const cmd = `"${PYTHON}" "${CLI}" --image "${safePdfPath}" --lang ${langOpt} --dpi ${dpiOpt} --format ${fmtOpt}`;

    const stdout = execSync(cmd, {
      cwd: PROJECT_DIR,
      timeout: 300_000,
      encoding: "utf-8",
      maxBuffer: 50 * 1024 * 1024,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    }).trim();

    if (!stdout) return "PDF OCR 返回空结果";

    // 4. JSON 格式时格式化输出
    if (fmtOpt === "json") {
      try {
        const pages = JSON.parse(stdout);
        if (Array.isArray(pages)) {
          const parts = pages.map((p) => {
            const header = `--- 第 ${p.page} 页 ---`;
            const text = p.text || blocksToText(p.blocks);
            return `${header}\n${text}`;
          });
          const result = parts.join("\n\n");

          const jsonPath = path.join(TEMP_DIR, `ocr_pdf_raw_${Date.now()}.json`);
          writeFileSync(jsonPath, JSON.stringify(pages, null, 2), "utf-8");
          await toolCtx.stageFile({
            sessionPath: "ocr_pdf_result.json",
            filePath: jsonPath,
            label: "PDF OCR 原始结果 (JSON)",
          });

          return result;
        }
      } catch {
        // 解析失败则退回纯文本
      }
    }

    // 5. 非 JSON 格式直接返回
    return stdout;
  } catch (err) {
    const msg = err.stderr || err.message || String(err);
    return `PDF OCR 执行失败：\n${msg.slice(0, 2000)}`;
  } finally {
    if (temporary) tryCleanup(safePdfPath);
  }
}
