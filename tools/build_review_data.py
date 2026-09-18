"""从 analysis_three_runs.xlsx 生成审核队列 review/data.json。

用法:
    python tools/build_review_data.py
    python tools/build_review_data.py --excel analysis_three_runs.xlsx --out review/data.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

MODEL_KEY = {
    "qwen3-vl-plus": "vl",
    "qwen3.8-flash": "flash",
    "qwen3.8-max-0902": "max",
}

SHEET_BUCKET = {
    "多数285": "majority",
    "分歧126": "split",
}


def build_questions(excel_path: Path) -> list[dict]:
    xl = pd.ExcelFile(excel_path)
    questions: list[dict] = []

    for sheet_name, bucket in SHEET_BUCKET.items():
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
            key = MODEL_KEY.get(model_name)
            if key is None:
                # fallback: infer from name
                low = model_name.lower()
                if "flash" in low:
                    key = "flash"
                elif "max" in low:
                    key = "max"
                else:
                    key = "vl"

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

        # majority first (sheet order), then id ascending within bucket
        items = sorted(by_id.values(), key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else str(x["id"]))
        for item in items:
            for k in ("vl", "flash", "max"):
                item["answers"].setdefault(k, {"model": k, "answer": ""})
            questions.append(item)

    return questions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--excel", default=str(ROOT / "analysis_three_runs.xlsx"))
    p.add_argument("--out", default=str(ROOT / "review" / "data.json"))
    args = p.parse_args()

    excel_path = Path(args.excel)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    questions = build_questions(excel_path)
    payload = {
        "version": 1,
        "source": excel_path.name,
        "count": len(questions),
        "questions": questions,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    n_maj = sum(1 for q in questions if q["bucket"] == "majority")
    n_split = sum(1 for q in questions if q["bucket"] == "split")
    print(f"写出 {out_path} | 共 {len(questions)} 题（多数 {n_maj} + 分歧 {n_split}）")


if __name__ == "__main__":
    main()
