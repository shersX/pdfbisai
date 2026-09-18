"""Profile remaining score-up opportunities from baseline_82."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
tests = pd.read_excel(ROOT / "tests.xlsx")
sub = pd.read_excel(ROOT / "submissions" / "baseline_82.xlsx", dtype=str, keep_default_na=False)
sub["id"] = sub["id"].astype(str)
amap = dict(zip(sub["id"], sub["answer"]))
tests["id"] = tests["id"].astype(str)
tests["answer"] = tests["id"].map(amap).fillna("")
tests["fmt"] = tests["answer_format"].astype(str).str.strip().str.lower()
tests["qt"] = tests["question_type"].astype(str).str.strip().str.lower()
tests["q"] = tests["question"].astype(str)

lines: list[str] = []
lines.append(f"total={len(tests)} score_unit={100/len(tests):.4f} gap_to_82.5={(82.5-82)*len(tests)/100:.1f} questions")

lines.append("\n=== by question_type ===")
lines.append(tests["qt"].value_counts().to_string())
lines.append("\n=== by answer_format ===")
lines.append(tests["fmt"].value_counts(dropna=False).to_string())

# blankish
blank_mask = tests["answer"].str.strip().isin(["", '""', '[""]', "[]"])
blank = tests[blank_mask]
lines.append(f"\n=== blankish answers n={len(blank)} ===")
for _, r in blank.iterrows():
    lines.append(f"id={r['id']} qt={r['qt']} fmt={r['fmt']} ans={r['answer']!r} q={r['q'][:60]}")

# yes/no distribution
yn = tests[tests["answer"].isin(["是", "否", "yes", "no", "Yes", "No", "true", "false", "True", "False"])]
lines.append(f"\n=== yes/no style answers n={len(yn)} ===")
lines.append(str(Counter(yn["answer"])))
yn_q = tests[tests["q"].str.contains("是否|请判断", na=False)]
lines.append(f"questions containing 是否/请判断: {len(yn_q)}")
odd_yn = yn_q[~yn_q["answer"].isin(["是", "否"])]
lines.append(f"those NOT answered 是/否: {len(odd_yn)}")
for _, r in odd_yn.head(30).iterrows():
    lines.append(f"  id={r['id']} ans={r['answer']!r} q={r['q'][:70]}")

# structure geometry
st = tests[tests["qt"] == "structure"]
bad_st = 0
geom = 0
geom_ids = []
for _, r in st.iterrows():
    try:
        o = json.loads(r["answer"])
        assert isinstance(o, dict) and "cells" in o
        rc, cc = int(o["row_count"]), int(o["col_count"])
        violated = False
        for c in o["cells"]:
            if (
                c["row"] + c["rowspan"] > rc
                or c["col"] + c["colspan"] > cc
                or c["row"] < 0
                or c["col"] < 0
            ):
                violated = True
                break
        if violated:
            geom += 1
            geom_ids.append(r["id"])
    except Exception:
        bad_st += 1
        geom_ids.append(r["id"])
lines.append(f"\n=== structure n={len(st)} invalid_or_unparseable={bad_st} geom_violation={geom} ===")
lines.append(f"geom_ids={geom_ids[:40]}")

# thousand comma / spaces
comma = tests[tests["answer"].str.contains(r"\d,\d{3}", regex=True, na=False)]
lines.append(f"\nanswers_with_thousand_comma={len(comma)}")
for _, r in comma.head(15).iterrows():
    lines.append(f"  id={r['id']} ans={r['answer'][:80]}")

# trailing .0 / space issues in scalar numbers
num_fmt = tests[tests["fmt"] == "number"]
lines.append(f"\n=== number format questions n={len(num_fmt)} ===")
weird_num = []
for _, r in num_fmt.iterrows():
    a = r["answer"].strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", a):
        weird_num.append((r["id"], a, r["q"][:50]))
lines.append(f"number_answers_not_plain_numeric={len(weird_num)}")
for item in weird_num[:20]:
    lines.append(f"  id={item[0]} ans={item[1]!r} q={item[2]}")

# language leftovers
lang = tests[tests["q"].str.contains("该表主要使用哪种语言", na=False)]
lines.append(f"\n=== language question answers ===")
lines.append(str(Counter(lang["answer"])))

# json_array length anomalies: single empty
ja = tests[tests["fmt"] == "json_array"]
empty_arr = []
for _, r in ja.iterrows():
    try:
        o = json.loads(r["answer"])
        if o == [""] or o == []:
            empty_arr.append((r["id"], r["answer"], r["q"][:60]))
    except Exception:
        empty_arr.append((r["id"], "INVALID", r["q"][:60]))
lines.append(f"\n=== json_array empty-ish n={len(empty_arr)} ===")
for item in empty_arr:
    lines.append(f"  id={item[0]} ans={item[1]!r} q={item[2]}")

# review disagreement still relevant
review_path = ROOT / "review" / "data.json"
if review_path.exists():
    d = json.load(review_path.open(encoding="utf-8"))
    qs = d["questions"]
    lines.append(f"\n=== review data n={len(qs)} buckets={Counter(q.get('bucket') for q in qs)} ===")
    # answers where current != all three models agreeing
    diverge_now = 0
    for q in qs:
        cur = amap.get(str(q["id"]), "")
        vals = [q["answers"][k]["answer"] for k in ("vl", "flash", "max") if k in q["answers"]]
        if cur and vals and cur not in vals:
            diverge_now += 1
    lines.append(f"current_answer_not_in_any_of_three_models={diverge_now}")

out = ROOT / "submissions" / "scoreup_ideas_scan.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
print("\n".join(lines[:60]))
