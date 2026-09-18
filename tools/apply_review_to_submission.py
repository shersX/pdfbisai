"""将人工审核的多数派判定 + 手动覆盖写入 submission.xlsx。

规则:
1. 以当前 submission.xlsx 为底账（含一致497与原投票结果）
2. 用 outputs/review_decisions.json 覆盖已审 majority
3. 应用 --override id=answer
4. 写出根目录与 outputs/submission.xlsx
5. 生成 retry_split_ids.txt（分歧126，供重跑）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def excel_answer(text: str) -> str:
    if text == "" or str(text).lower() in {"nan", "none", "null"}:
        return '""'
    return text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--submission", default=str(ROOT / "submission.xlsx"))
    p.add_argument("--decisions", default=str(ROOT / "outputs" / "review_decisions.json"))
    p.add_argument("--data", default=str(ROOT / "review" / "data.json"))
    p.add_argument("--out", default=str(ROOT / "submission.xlsx"))
    p.add_argument(
        "--override",
        action="append",
        default=[],
        help="手动覆盖，格式 id=answer，可多次。answer 中可用 \\n",
    )
    args = p.parse_args()

    sub = pd.read_excel(args.submission)
    if "id" not in sub.columns or "answer" not in sub.columns:
        raise ValueError("submission 需要 id/answer 列")
    sub["id"] = sub["id"].astype(int)
    answers = {int(r.id): "" if pd.isna(r.answer) else str(r.answer) for _, r in sub.iterrows()}

    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    n_dec = 0
    for qid, item in decisions.items():
        answers[int(qid)] = str(item.get("answer", ""))
        n_dec += 1

    n_over = 0
    for item in args.override:
        if "=" not in item:
            raise ValueError(f"override 格式应为 id=answer，收到: {item}")
        qid_s, ans = item.split("=", 1)
        answers[int(qid_s.strip())] = ans.encode("utf-8").decode("unicode_escape") if "\\u" in ans else ans
        # simpler: just use ans as-is from command line; PowerShell may mangle. Prefer JSON file for Chinese.
        answers[int(qid_s.strip())] = ans
        n_over += 1

    # rebuild frame in tests.xlsx order
    tests = pd.read_excel(ROOT / "tests.xlsx")
    rows = []
    for _, r in tests.iterrows():
        qid = int(r["id"])
        rows.append({"id": qid, "answer": excel_answer(answers.get(qid, ""))})
    out_df = pd.DataFrame(rows, columns=["id", "answer"])

    out_path = Path(args.out)
    out_df.to_excel(out_path, index=False)
    out_df.to_excel(ROOT / "outputs" / "submission.xlsx", index=False)

    # split ids for rerun
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    split_ids = [str(q["id"]) for q in data.get("questions", []) if q.get("bucket") == "split"]
    split_path = ROOT / "retry_split_ids.txt"
    split_path.write_text("\n".join(split_ids) + "\n", encoding="utf-8")

    # majority coverage report
    maj_ids = [q["id"] for q in data.get("questions", []) if q.get("bucket") == "majority"]
    missing_maj = [i for i in maj_ids if str(i) not in decisions]
    print(f"写入 {out_path} / outputs/submission.xlsx | 共 {len(out_df)} 题")
    print(f"应用审核判定 {n_dec} | 手动覆盖 {n_over}")
    print(f"未审 majority 保留原答案: {missing_maj}")
    print(f"分歧重跑名单 {len(split_ids)} -> {split_path}")


if __name__ == "__main__":
    main()
