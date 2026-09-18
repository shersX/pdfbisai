"""从 analysis_three_runs.xlsx 生成审核队列 JSON。

用法:
    python tools/build_review_data.py
    python tools/build_review_data.py --bucket split --out review/data_split.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# 精确映射优先；含 "max"+"split"/"retry" 的第四轮不要落到 max
MODEL_KEY = {
    "qwen3-vl-plus": "vl",
    "qwen3.8-flash": "flash",
    "qwen3.8-max-0902": "max",
    "qwen3.8-Max-split-retry": "retry",
}

ANSWER_ORDER = ("vl", "flash", "max", "retry")

SHEET_BUCKET = {
    "多数285": "majority",
    "分歧126": "split",
}


def model_to_key(model_name: str) -> str:
    name = model_name.strip()
    if name in MODEL_KEY:
        return MODEL_KEY[name]
    low = name.lower()
    if "split" in low or "retry" in low:
        return "retry"
    if "flash" in low:
        return "flash"
    if "max" in low:
        return "max"
    return "vl"


def build_questions(excel_path: Path, *, buckets: set[str] | None = None) -> list[dict]:
    xl = pd.ExcelFile(excel_path)
    questions: list[dict] = []

    for sheet_name, bucket in SHEET_BUCKET.items():
        if buckets is not None and bucket not in buckets:
            continue
        if sheet_name not in xl.sheet_names:
            raise ValueError(f"缺少 sheet: {sheet_name}，实际有 {xl.sheet_names}")
        df = pd.read_excel(xl, sheet_name=sheet_name)
        required = {"id", "file_name", "question_type", "question", "model", "answer"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{sheet_name} 缺少列: {sorted(missing)}")

        by_id: dict[str, dict] = {}
        for _, row in df.iterrows():
            qid = str(row["id"])
            model_name = str(row["model"]).strip()
            key = model_to_key(model_name)

            if qid not in by_id:
                by_id[qid] = {
                    "id": int(row["id"]) if str(row["id"]).isdigit() else row["id"],
                    "file_name": "" if pd.isna(row["file_name"]) else str(row["file_name"]),
                    "question_type": "" if pd.isna(row["question_type"]) else str(row["question_type"]),
                    "question": "" if pd.isna(row["question"]) else str(row["question"]),
                    "bucket": bucket,
                    "answers": {},
                }
            by_id[qid]["answers"][key] = {
                "model": model_name,
                "answer": "" if pd.isna(row["answer"]) else str(row["answer"]),
            }

        items = sorted(
            by_id.values(),
            key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else str(x["id"]),
        )
        for item in items:
            # 多数题只有三方；分歧题补齐四轮键（缺则空）
            keys = ("vl", "flash", "max", "retry") if bucket == "split" else ("vl", "flash", "max")
            for k in keys:
                item["answers"].setdefault(k, {"model": k, "answer": ""})
            # 稳定顺序，便于前端展示
            item["answers"] = {
                k: item["answers"][k] for k in keys if k in item["answers"]
            }
            questions.append(item)

    return questions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--excel", default=str(ROOT / "analysis_three_runs.xlsx"))
    p.add_argument("--out", default=str(ROOT / "review" / "data.json"))
    p.add_argument(
        "--bucket",
        choices=("all", "majority", "split"),
        default="all",
        help="只导出指定队列；split 为四轮分歧审批",
    )
    args = p.parse_args()

    excel_path = Path(args.excel)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    buckets = None if args.bucket == "all" else {args.bucket}
    questions = build_questions(excel_path, buckets=buckets)
    payload = {
        "version": 2 if args.bucket == "split" else 1,
        "source": excel_path.name,
        "bucket_filter": args.bucket,
        "choices": list(ANSWER_ORDER) if args.bucket == "split" else ["vl", "flash", "max"],
        "count": len(questions),
        "questions": questions,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    n_maj = sum(1 for q in questions if q["bucket"] == "majority")
    n_split = sum(1 for q in questions if q["bucket"] == "split")
    print(f"写出 {out_path} | 共 {len(questions)} 题（多数 {n_maj} + 分歧 {n_split}）")


if __name__ == "__main__":
    main()
