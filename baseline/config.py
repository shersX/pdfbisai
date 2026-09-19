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
    mineru_token: str
    mineru_api_base: str
    mineru_model_version: str
    mineru_llm_model: str
    mineru_md_max_chars: int


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
    raw_mineru = os.getenv("MINERU_API_URL", "https://mineru.net/api/v4").strip()
    mineru_base = _normalize_mineru_base(raw_mineru)
    mineru_llm = os.getenv("MINERU_LLM_MODEL", "").strip() or model
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
        mineru_token=os.getenv("MINERU_API_KEY", "").strip(),
        mineru_api_base=mineru_base,
        mineru_model_version=os.getenv("MINERU_MODEL_VERSION", "vlm").strip() or "vlm",
        mineru_llm_model=mineru_llm,
        mineru_md_max_chars=max(4000, int(os.getenv("MINERU_MD_MAX_CHARS", "80000"))),
    )


def _normalize_mineru_base(url: str) -> str:
    base = url.strip().rstrip("/")
    for suffix in ("/extract/task", "/file-urls/batch", "/extract-results/batch"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base
