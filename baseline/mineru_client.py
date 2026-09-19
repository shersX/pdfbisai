"""MinerU 精准解析 API：本地上传 → 轮询 → 下载 zip → 抽出 Markdown。"""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

BATCH_LIMIT = 50
DONE_STATES = {"done"}
FAIL_STATES = {"failed"}
WAIT_STATES = {"waiting-file", "pending", "running", "converting"}


def _safe_data_id(file_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._-")
    return (stem or "file")[:128]


class MinerUError(RuntimeError):
    pass


class MinerUClient:
    def __init__(self, token: str, api_base: str):
        if not token:
            raise MinerUError("未设置 MINERU_API_KEY。")
        self.token = token
        self.api_base = api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def submit_local_files(
        self,
        paths: list[Path],
        *,
        model_version: str = "vlm",
        language: str = "ch",
        is_ocr: bool = True,
    ) -> str:
        if not paths:
            raise MinerUError("没有待上传文件")
        if len(paths) > BATCH_LIMIT:
            raise MinerUError(f"单批最多 {BATCH_LIMIT} 个文件，收到 {len(paths)}")

        payload = {
            "files": [
                {
                    "name": p.name,
                    "data_id": _safe_data_id(p.name),
                    "is_ocr": is_ocr,
                }
                for p in paths
            ],
            "model_version": model_version,
            "enable_table": True,
            "enable_formula": True,
            "language": language,
        }
        resp = requests.post(
            f"{self.api_base}/file-urls/batch",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        body = _json_or_error(resp, "申请上传链接")
        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or []
        if not batch_id or len(urls) != len(paths):
            raise MinerUError(f"上传链接数量不匹配: {body}")

        for path, url in zip(paths, urls, strict=True):
            with path.open("rb") as f:
                put = requests.put(url, data=f, timeout=300)
            if put.status_code not in (200, 201):
                raise MinerUError(f"上传失败 {path.name}: HTTP {put.status_code} {put.text[:200]}")
        return str(batch_id)

    def poll_batch(
        self,
        batch_id: str,
        *,
        timeout: int = 1800,
        interval: float = 5.0,
    ) -> list[dict[str, Any]]:
        url = f"{self.api_base}/extract-results/batch/{batch_id}"
        start = time.time()
        last: list[dict[str, Any]] = []
        while time.time() - start < timeout:
            resp = requests.get(url, headers=self._headers(), timeout=60)
            body = _json_or_error(resp, "查询批量任务")
            last = list((body.get("data") or {}).get("extract_result") or [])
            if last and all(str(item.get("state", "")).lower() in DONE_STATES | FAIL_STATES for item in last):
                return last
            pending = [
                str(item.get("file_name") or item.get("data_id") or "?")
                for item in last
                if str(item.get("state", "")).lower() not in DONE_STATES | FAIL_STATES
            ]
            elapsed = int(time.time() - start)
            print(f"  [mineru {elapsed}s] batch={batch_id[:8]}… 未完成 {len(pending)}/{len(last) or '?'}")
            time.sleep(interval)
        raise MinerUError(f"轮询超时 batch_id={batch_id} last={last}")

    def download_markdown(self, zip_url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        resp = requests.get(zip_url, timeout=180)
        if resp.status_code != 200:
            raise MinerUError(f"下载 zip 失败 HTTP {resp.status_code}")
        zpath = dest_dir / "result.zip"
        zpath.write_bytes(resp.content)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(dest_dir)
        md = _find_full_md(dest_dir)
        if md is None:
            raise MinerUError(f"zip 中没有 full.md: {dest_dir}")
        return md


def _json_or_error(resp: requests.Response, action: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise MinerUError(f"{action} 非 JSON: HTTP {resp.status_code} {resp.text[:300]}") from exc
    if resp.status_code != 200 or int(body.get("code", -1)) != 0:
        raise MinerUError(f"{action} 失败: HTTP {resp.status_code} {json.dumps(body, ensure_ascii=False)[:500]}")
    return body


def _find_full_md(root: Path) -> Path | None:
    exact = list(root.rglob("full.md"))
    if exact:
        return exact[0]
    mds = list(root.rglob("*.md"))
    return mds[0] if mds else None
