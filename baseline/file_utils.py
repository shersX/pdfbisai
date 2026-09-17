from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pymupdf
from PIL import Image


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

_lock_guard = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


def _lock_for(key: str) -> threading.Lock:
    with _lock_guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _path_locks[key] = lock
        return lock


def resolve_file(files_dir: Path, file_name: str) -> Path:
    path = files_dir / file_name
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {path}")
    return path


def pdf_to_images(
    pdf_path: Path,
    cache_dir: Path,
    max_pages: int,
    zoom: float,
) -> list[Path]:
    """Render PDF pages to cached PNG files and return image paths."""
    key = hashlib.md5(f"{pdf_path.resolve()}|{max_pages}|{zoom}".encode()).hexdigest()[:12]
    out_dir = cache_dir / "pdf_pages" / f"{pdf_path.stem}_{key}"
    lock = _lock_for(str(out_dir))

    with lock:
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(out_dir.glob("page_*.png"))
        if existing:
            return existing[:max_pages]

        doc = pymupdf.open(pdf_path)
        paths: list[Path] = []
        try:
            page_count = min(len(doc), max_pages)
            matrix = pymupdf.Matrix(zoom, zoom)
            for i in range(page_count):
                pix = doc.load_page(i).get_pixmap(matrix=matrix, alpha=False)
                out = out_dir / f"page_{i + 1:03d}.png"
                pix.save(out.as_posix())
                paths.append(out)
        finally:
            doc.close()
        return paths


def load_media_as_image_paths(
    file_path: Path,
    cache_dir: Path,
    max_pdf_pages: int,
    pdf_zoom: float,
) -> list[Path]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return pdf_to_images(file_path, cache_dir, max_pdf_pages, pdf_zoom)
    if suffix in IMAGE_EXTS:
        if suffix == ".webp":
            out = cache_dir / "images" / f"{file_path.stem}.png"
            lock = _lock_for(str(out))
            with lock:
                out.parent.mkdir(parents=True, exist_ok=True)
                if not out.exists():
                    Image.open(file_path).convert("RGB").save(out)
            return [out]
        return [file_path]
    raise ValueError(f"不支持的文件类型: {file_path}")
