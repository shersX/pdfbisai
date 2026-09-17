from __future__ import annotations

import argparse

from baseline.config import get_settings
from baseline.runner import run_baseline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multimodal table recognition baseline (Qwen-VL)")
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 题，便于冒烟测试")
    p.add_argument("--ids", type=str, default=None, help="只跑指定 id，逗号分隔，如 1,2,3")
    p.add_argument("--ids-file", type=str, default=None, help="从文本文件读取 id 列表（每行一个）")
    p.add_argument("--no-resume", action="store_true", help="忽略 checkpoint，重新作答")
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="并发数，默认读取环境变量 MAX_WORKERS（当前默认 3）",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ids = None
    if args.ids:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    elif args.ids_file:
        from pathlib import Path

        lines = Path(args.ids_file).read_text(encoding="utf-8").splitlines()
        ids = [int(x.strip()) for x in lines if x.strip()]

    settings = get_settings()
    out = run_baseline(
        settings,
        limit=args.limit,
        ids=ids,
        resume=not args.no_resume,
        max_workers=args.workers,
    )
    print(f"提交文件已生成: {out}")
    summary = settings.output_dir / "token_usage_summary.json"
    if summary.exists():
        print(f"Token 汇总: {summary}")


if __name__ == "__main__":
    main()
