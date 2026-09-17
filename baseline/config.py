from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    files_dir: Path
    tests_path: Path
    output_dir: Path
    cache_dir: Path
    max_pdf_pages: int
    pdf_zoom: float
    max_workers: int


def get_settings() -> Settings:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "未设置 DASHSCOPE_API_KEY。请复制 .env.example 为 .env 并填入阿里云百炼 API Key。"
        )
    base_url = (
        os.getenv("DASHSCOPE_BASE_URL")
        or os.getenv("DASHSCOPE_HTTP_BASE_URL")
        or "https://dashscope.aliyuncs.com/api/v1"
    ).strip().rstrip("/")
    model = os.getenv("QWEN_VL_MODEL", "qwen-vl-max").strip()
    # 每个模型独立输出子目录，避免不同模型的 checkpoint 混在一起
    output_subdir = os.getenv("OUTPUT_SUBDIR", model).strip()
    return Settings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        files_dir=ROOT / "files",
        tests_path=ROOT / "tests.xlsx",
        output_dir=ROOT / "outputs" / output_subdir,
        cache_dir=ROOT / "cache",
        max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "8")),
        pdf_zoom=float(os.getenv("PDF_ZOOM", "2.0")),
        max_workers=max(1, int(os.getenv("MAX_WORKERS", "3"))),
    )
