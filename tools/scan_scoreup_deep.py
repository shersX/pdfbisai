"""Deeper scan for high-ROI format traps."""
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
tests["a"] = tests["id"].map(amap).fillna("")
tests["q"] = tests["question"].astype(str)
tests["fmt"] = tests["answer_format"].astype(str).str.strip().str.lower()
tests["qt"] = tests["question_type"].astype(str)

lines = []

# European decimal comma in answers (not JSON separators)
euro = []
for _, r in tests.iterrows():
    a = r["a"]
    # scalar like 9,3 or inside JSON string "9,3"
    if re.search(r'(?<![\"\d])\d+,\d+(?![\"\d])', a) or re.search(r'"\d+,\d+"', a):
        euro.append(r)
    if a.count(",") and r["fmt"] == "number" and re.fullmatch(r"-?\d+,\d+", a.strip()):
        euro.append(r)
# dedupe
seen = set()
lines.append("=== european-style decimal candidates ===")
for r in euro:
    if r["id"] in seen:
        continue
    seen.add(r["id"])
    lines.append(f"id={r['id']} fmt={r['fmt']} ans={r['a']!r} q={r['q'][:70]}")

# percent answers
lines.append("\n=== answers containing % ===")
pct = tests[tests["a"].str.contains("%", na=False)]
lines.append(f"n={len(pct)}")
styles = Counter()
for _, r in pct.iterrows():
    styles[r["fmt"]] += 1
lines.append(str(styles))
for _, r in pct.head(25).iterrows():
    lines.append(f"id={r['id']} fmt={r['fmt']} ans={r['a'][:100]}")

# '--' or placeholder answers
lines.append("\n=== placeholder-like answers ===")
for _, r in tests.iterrows():
    a = r["a"].strip()
    if a in {"--", "-", "N/A", "na", "无", "未知", "null", "None", "/", "—", "–"}:
        lines.append(f"id={r['id']} fmt={r['fmt']} ans={a!r} q={r['q'][:70]}")

# true/false vs 是/否 mix inside arrays
lines.append("\n=== boolean token variants in answers ===")
for tok in ["true", "false", "True", "False", "YES", "NO", "Yes", "No"]:
    hit = tests[tests["a"].str.contains(tok, na=False, regex=False)]
    if len(hit):
        lines.append(f"token={tok!r} n={len(hit)} ids={hit['id'].tolist()[:15]}")

# structure: local vs full - count cells vs row*col
lines.append("\n=== structure cell density ===")
st = tests[tests["qt"] == "structure"]
for _, r in st.iterrows():
    try:
        o = json.loads(r["a"])
        n = len(o.get("cells", []))
        area = int(o["row_count"]) * int(o["col_count"])
        q = r["q"]
        local = any(k in q for k in ["前", "局部", "只恢复", "第一行", "前1", "前 1", "前3", "前 3"])
        lines.append(
            f"id={r['id']} cells={n} area={area} local_hint={local} "
            f"rc={o['row_count']} cc={o['col_count']} q={q[:50]}"
        )
    except Exception as e:
        lines.append(f"id={r['id']} ERR {e}")

# trailing zeros / .00 in scalar number answers
lines.append("\n=== number answers with trailing zeros ===")
num = tests[tests["fmt"] == "number"]
for _, r in num.iterrows():
    a = r["a"].strip()
    if re.fullmatch(r"-?\d+\.0+", a) or (a.endswith("0") and "." in a and re.fullmatch(r"-?\d+\.\d+", a)):
        if a.endswith("0") and not a.endswith(".0") and not re.search(r"\.\d*0$", a):
            continue
        if re.search(r"0$", a) and "." in a:
            lines.append(f"id={r['id']} ans={a!r}")

# spaces in answers
lines.append("\n=== answers with leading/trailing/double spaces or fullwidth ===")
n_space = 0
for _, r in tests.iterrows():
    a = r["a"]
    if a != a.strip() or "  " in a or "\u3000" in a or "\xa0" in a:
        n_space += 1
        if n_space <= 20:
            lines.append(f"id={r['id']} ans={a!r}")
lines.append(f"total_spacey={n_space}")

# id 19 and nearby empty thinking
lines.append("\n=== suspicious empty / nearly empty ===")
for _, r in tests.iterrows():
    a = r["a"].strip()
    if a in {"", '""', '[""]', "[]", "--"}:
        lines.append(f"id={r['id']} qt={r['qt']} fmt={r['fmt']} file={r['file_name']} ans={a!r} q={r['q']}")

out = ROOT / "submissions" / "scoreup_ideas_deep.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("wrote", out)
print("euro_n", len(seen) if 'seen' in dir() else "")
