"""Flip quoted pure numbers inside json_array answers to unquoted JSON numbers.

Preserves the exact digit text (e.g. "2794275324.10" -> 2794275324.10),
only removing the surrounding quotes. Non-json_array rows are untouched.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Match a JSON string whose entire content is a pure number.
QUOTED_NUM = re.compile(r'"(-?\d+(?:\.\d+)?)"')


def unquote_numbers_in_array(answer: str) -> tuple[str, int]:
    s = (answer or "").strip()
    try:
        obj = json.loads(s)
    except Exception:
        return answer, 0
    if not isinstance(obj, list):
        return answer, 0

    flipped = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal flipped
        flipped += 1
        return m.group(1)  # bare number text, quotes removed

    new = QUOTED_NUM.sub(repl, s)
    if flipped == 0:
        return answer, 0

    # Sanity: still valid JSON array, and every flipped token is a JSON number.
    try:
        again = json.loads(new)
    except Exception:
        return answer, 0
    if not isinstance(again, list):
        return answer, 0
    return new, flipped


def main() -> None:
    baseline_path = ROOT / "submissions" / "baseline_82.xlsx"
    if not baseline_path.exists():
        raise SystemExit(f"missing {baseline_path}")

    tests = pd.read_excel(ROOT / "tests.xlsx")
    fmt = tests["answer_format"].astype(str).str.strip().str.lower()
    ja_ids = set(tests.loc[fmt == "json_array", "id"].astype(str))

    df = pd.read_excel(baseline_path, dtype=str, keep_default_na=False)
    df["id"] = df["id"].astype(str)

    diffs: list[tuple[str, str, str, int]] = []
    for i, row in df.iterrows():
        qid = str(row["id"])
        if qid not in ja_ids:
            continue
        old = str(row["answer"])
        new, n = unquote_numbers_in_array(old)
        if n:
            df.at[i, "answer"] = new
            diffs.append((qid, old, new, n))

    out_xlsx = ROOT / "submissions" / "v_JA_unquote_nums.xlsx"
    out_diff = ROOT / "submissions" / "v_JA_unquote_nums.diff.csv"
    save = df.copy()
    try:
        save["id"] = save["id"].astype(int)
    except ValueError:
        pass
    save.to_excel(out_xlsx, index=False)

    with out_diff.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "n_flipped", "baseline", "variant"])
        for qid, old, new, n in sorted(diffs, key=lambda x: int(x[0])):
            w.writerow([qid, n, old, new])

    base = pd.read_excel(baseline_path, dtype=str, keep_default_na=False)
    base["id"] = base["id"].astype(str)
    merged = base.merge(df, on="id", suffixes=("_b", "_v"))
    changed = merged["answer_b"] != merged["answer_v"]
    unexpected = merged[changed & ~merged["id"].isin({d[0] for d in diffs})]
    print(f"json_array_ids={len(ja_ids)}")
    print(f"questions_changed={len(diffs)}")
    print(f"number_tokens_flipped={sum(d[3] for d in diffs)}")
    print(f"unexpected_other_changes={len(unexpected)}")
    print(f"wrote {out_xlsx.relative_to(ROOT)}")
    print(f"wrote {out_diff.relative_to(ROOT)}")
    for qid, old, new, n in sorted(diffs, key=lambda x: int(x[0])):
        print(f"  id={qid} flipped={n}")
        print(f"    old={old}")
        print(f"    new={new}")


if __name__ == "__main__":
    main()
