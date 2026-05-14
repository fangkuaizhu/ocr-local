"""
OCR 队列管理器：模型常驻，避免每次重载 PaddleOCR

架构:
  Agent ── enqueue ──►  queue/pending/  ──►  Daemon ──►  queue/done/

用法:
  # 提交任务
  python ocr_cli.py --image foo.png --enqueue

  # 守护进程
  python ocr_cli.py --daemon
"""

import json
import shutil
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

_QUEUE_BASE = Path(__file__).parent / "queue"
PENDING_DIR = _QUEUE_BASE / "pending"
RUNNING_DIR = _QUEUE_BASE / "running"
DONE_DIR = _QUEUE_BASE / "done"
FAILED_DIR = _QUEUE_BASE / "failed"
ALL_DIRS = [PENDING_DIR, RUNNING_DIR, DONE_DIR, FAILED_DIR]
LOCK_FILE = _QUEUE_BASE / ".daemon.lock"
JOB_PREFIX = "ocr_job_"


def _ensure_dirs():
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def _is_daemon_alive():
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text().strip())
        import os as _os
        _os.kill(pid, 0)
        return True
    except:
        return False


# ═══ 提交 ═══

def enqueue(image_path: str, lang: str = "ch") -> str:
    """提交 OCR 任务，返回 job_id"""
    _ensure_dirs()
    job_id = f"{JOB_PREFIX}{uuid.uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "image_path": str(Path(image_path).resolve()),
        "lang": lang,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }
    job_file = PENDING_DIR / f"{job_id}.json"
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job_id


def queue_status() -> dict:
    _ensure_dirs()
    pending = sorted(PENDING_DIR.glob(f"{JOB_PREFIX}*.json"))
    running = sorted(RUNNING_DIR.glob(f"{JOB_PREFIX}*.json"))
    return {
        "pending": len(pending),
        "pending_jobs": [j.stem for j in pending],
        "running": len(running),
        "running_jobs": [j.stem for j in running],
        "done": len(list(DONE_DIR.glob(f"{JOB_PREFIX}*.json"))),
        "failed": len(list(FAILED_DIR.glob(f"{JOB_PREFIX}*.json"))),
        "daemon_alive": _is_daemon_alive(),
    }


def get_job_result(job_id: str) -> dict | None:
    """如果任务完成，返回结果；否则返回 None"""
    for d in [DONE_DIR, FAILED_DIR]:
        f = d / f"{job_id}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    return None


# ═══ 守护进程 ═══

class OcrDaemon:
    """常驻守护进程：加载模型一次，轮询队列处理任务"""

    MAX_DONE_JOBS = 500  # 保留最近完成的作业数

    def __init__(self):
        self.running = True

    def _acquire_lock(self) -> bool:
        """获取排他锁。已存在有效 daemon 时返回 False"""
        if _is_daemon_alive():
            print("[daemon] 已有守护进程在运行，退出", flush=True)
            return False
        LOCK_FILE.write_text(str(__import__("os").getpid()))
        return True

    def _recover_orphans(self):
        """重启时恢复 running 目录中的孤儿作业 → 回到 pending"""
        orphans = sorted(RUNNING_DIR.glob(f"{JOB_PREFIX}*.json"))
        for f in orphans:
            try:
                shutil.move(str(f), str(PENDING_DIR / f.name))
                print(f"[daemon] 恢复孤儿作业: {f.stem}", flush=True)
            except Exception as e:
                print(f"[daemon] 恢复失败: {f.stem} → {e}", flush=True)

    def _cleanup_old_jobs(self):
        """清理旧的 done/failed 作业"""
        for d in [DONE_DIR, FAILED_DIR]:
            jobs = sorted(d.glob(f"{JOB_PREFIX}*.json"), key=lambda x: x.stat().st_mtime)
            for f in jobs[:-self.MAX_DONE_JOBS]:
                try:
                    f.unlink()
                except Exception:
                    pass

    def run(self):
        _ensure_dirs()
        if not self._acquire_lock():
            return

        self._recover_orphans()
        print("[daemon] OCR 守护进程启动", flush=True)

        # 加载模型（只加载一次）
        from ocr_core import extract_text
        self.extract_text = extract_text
        # 预热：用极小图片触发 PaddleOCR 的首次模型加载，避免首任务等待
        import tempfile, numpy as np
        from PIL import Image
        tmp = Path(tempfile.gettempdir()) / "_ocr_warmup.png"
        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(tmp)
        try:
            extract_text(str(tmp), lang="ch")
        except:
            pass
        tmp.unlink(missing_ok=True)
        print("[daemon] PaddleOCR 模型加载完成，开始轮询", flush=True)

        try:
            self._poll_loop()
        finally:
            LOCK_FILE.unlink(missing_ok=True)

    def _poll_loop(self):
        while self.running:
            jobs = sorted(PENDING_DIR.glob(f"{JOB_PREFIX}*.json"))
            if not jobs:
                time.sleep(1)
                continue

            job_file = jobs[0]
            job = json.loads(job_file.read_text(encoding="utf-8"))

            # 移到 running
            running_file = RUNNING_DIR / job_file.name
            shutil.move(str(job_file), str(running_file))

            print(f"[daemon] 处理: {job['id']} → {job['image_path']}", flush=True)
            try:
                blocks = self.extract_text(job["image_path"], lang=job["lang"])
                result_path = DONE_DIR / f"{job['id']}.json"
                job["status"] = "done"
                job["result"] = blocks
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
                result_path.write_text(
                    json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                running_file.unlink()
                print(f"[daemon] 完成: {job['id']} ({len(blocks)} 行)", flush=True)
                self._cleanup_old_jobs()
            except Exception as e:
                fail_path = FAILED_DIR / f"{job['id']}.json"
                job["status"] = "failed"
                job["error"] = str(e)
                fail_path.write_text(
                    json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                running_file.unlink()
                print(f"[daemon] 失败: {job['id']} → {e}", flush=True)
                self._cleanup_old_jobs()


if __name__ == "__main__":
    OcrDaemon().run()
