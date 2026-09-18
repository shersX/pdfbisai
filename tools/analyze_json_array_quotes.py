"""Report json_array answers: quoted vs unquoted numbers."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NUM_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")


def load_submission() -> tuple[Path, pd.DataFrame]:
    for p in [
        ROOT / "submissions" / "baseline_82.xlsx",
        ROOT / "submission.xlsx",
        ROOT / "submissions" / "baseline_81.7.xlsx",
    ]:
        if p.exists():
            return p, pd.read_excel(p, dtype=str, keep_default_na=False)
    raise FileNotFoundError("no submission found")


def classify(ans: str) -> dict:
    s = (ans or "").strip()
    info = {
        "parse_ok": False,
        "n_elems": 0,
        "n_num_unquoted": 0,
        "n_num_quoted": 0,
        "n_non_num": 0,
        "has_empty_str": False,
        "elems_preview": "",
        "kind": "no_number",
    }
    try:
        obj = json.loads(s)
    except Exception:
        info["kind"] = "invalid_json"
        return info
    if not isinstance(obj, list):
        info["kind"] = "not_array"
        return info
    info["parse_ok"] = True
    info["n_elems"] = len(obj)
    previews: list[str] = []
    for x in obj:
        if isinstance(x, bool):
            info["n_non_num"] += 1
            previews.append(str(x).lower())
        elif isinstance(x, (int, float)):
            info["n_num_unquoted"] += 1
            previews.append(f"NUM:{x}")
        elif isinstance(x, str):
            if x == "":
                info["has_empty_str"] = True
                info["n_non_num"] += 1
                previews.append('""')
            elif NUM_TOKEN.fullmatch(x.strip()):
                info["n_num_quoted"] += 1
                previews.append(f"STRNUM:{x}")
            else:
                info["n_non_num"] += 1
                previews.append(f"STR:{x[:40]}")
        elif x is None:
            info["n_non_num"] += 1
            previews.append("null")
        else:
            info["n_non_num"] += 1
            previews.append(type(x).__name__)
    info["elems_preview"] = " | ".join(previews[:16])
    u, q = info["n_num_unquoted"], info["n_num_quoted"]
    if u and q:
        info["kind"] = "mixed_quoted"
    elif u:
        info["kind"] = "unquoted_only"
    elif q:
        info["kind"] = "quoted_only"
    else:
        info["kind"] = "no_number"
    return info


def main() -> None:
    sub_path, sub = load_submission()
    sub["id"] = sub["id"].astype(str)
    amap = dict(zip(sub["id"], sub["answer"]))

    tests = pd.read_excel(ROOT / "tests.xlsx")
    fmt = tests["answer_format"].astype(str).str.strip().str.lower()
    ja = tests[fmt == "json_array"].copy()
    ja["id"] = ja["id"].astype(str)
    ja["answer"] = ja["id"].map(amap)

    rows = []
    for _, r in ja.iterrows():
        c = classify(str(r["answer"]))
        rows.append(
            {
                "id": r["id"],
                "file_name": r["file_name"],
                "question_type": r["question_type"],
                "question": str(r["question"]),
                "answer": r["answer"],
                **c,
            }
        )
    out = pd.DataFrame(rows)

    lines: list[str] = []
    lines.append(f"submission={sub_path}")
    lines.append(f"json_array_total={len(out)}")
    lines.append(f"kinds={dict(Counter(out['kind']))}")
    lines.append(
        f"sum_unquoted_number_tokens={int(out['n_num_unquoted'].sum())} "
        f"sum_quoted_number_tokens={int(out['n_num_quoted'].sum())}"
    )
    lines.append(
        f"questions_with_any_number="
        f"{int(((out['n_num_unquoted'] + out['n_num_quoted']) > 0).sum())}"
    )
    lines.append("")

    order = [
        "quoted_only",
        "unquoted_only",
        "mixed_quoted",
        "no_number",
        "invalid_json",
        "not_array",
    ]
    for kind in order:
        subk = out[out["kind"] == kind].sort_values("id", key=lambda s: s.astype(int))
        if subk.empty:
            continue
        lines.append(f"=== {kind} n={len(subk)} ===")
        for _, rr in subk.iterrows():
            lines.append(
                f"id={rr['id']} file={rr['file_name']} type={rr['question_type']} "
                f"u={rr['n_num_unquoted']} q={rr['n_num_quoted']} elems={rr['n_elems']}"
            )
            lines.append(f"  preview: {rr['elems_preview']}")
            lines.append(f"  answer: {rr['answer']}")
            lines.append(f"  question: {rr['question']}")
            lines.append("")

    report_csv = ROOT / "submissions" / "json_array_number_quote_report.csv"
    report_txt = ROOT / "submissions" / "json_array_number_quote_report.txt"
    out.sort_values(["kind", "id"]).to_csv(report_csv, index=False, encoding="utf-8-sig")
    report_txt.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"wrote {report_csv}")
    print(f"wrote {report_txt}")


if __name__ == "__main__":
    main()
