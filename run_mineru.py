"""MinerU 解析 + 大模型：重跑「多数与分歧」中的 json_array 题。

用法:
    python run_mineru.py
    python run_mineru.py --parse-only
    python run_mineru.py --llm-only
    python run_mineru.py --limit 3
    python run_mineru.py --ids 5,9,19
"""

from __future__ import annotations

import argparse

from baseline.config import get_settings
from baseline.mineru_runner import run_mineru_pipeline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MinerU + LLM pipeline for json_array (多数与分歧)")
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 题")
    p.add_argument("--ids", type=str, default=None, help="只跑指定 id，逗号分隔")
    p.add_argument("--ids-file", type=str, default=None, help="从文本文件读取 id")
    p.add_argument("--no-resume", action="store_true", help="忽略已有解析/答案缓存")
    p.add_argument("--parse-only", action="store_true", help="只跑 MinerU 解析并落盘")
    p.add_argument("--llm-only", action="store_true", help="跳过解析，只用已落盘 Markdown 调大模型")
    p.add_argument("--workers", type=int, default=None, help="大模型并发数")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.parse_only and args.llm_only:
        raise SystemExit("--parse-only 与 --llm-only 不能同时用")

    ids = None
    if args.ids:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    elif args.ids_file:
        from pathlib import Path

        lines = Path(args.ids_file).read_text(encoding="utf-8").splitlines()
        ids = [int(x.strip()) for x in lines if x.strip()]

    settings = get_settings()
    out = run_mineru_pipeline(
        settings,
        limit=args.limit,
        ids=ids,
        resume=not args.no_resume,
        max_workers=args.workers,
        parse_only=args.parse_only,
        llm_only=args.llm_only,
    )
    if out is not None:
        print(f"提交切片已生成: {out}")


if __name__ == "__main__":
    main()
