"""Infer which non-unanimous questions must be correct from rounds 1-4 scores.

Rounds (from recode.txt):
  R1 vl-plus alone:     54.4 -> 494 correct
  R2 flash alone:       77.0 -> 699 correct
  R3 vote:              79.1 -> 718 correct
  R4 vote+max-split:    81.7 -> 742 correct
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Reuse numeric-ish equality similar to merge_vote for grouping
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def load_ckpt(path: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        done[str(o["id"])] = str(o.get("answer", "")).strip()
    return done


def canon(ans: str) -> str:
    s = (ans or "").strip()
    if not s:
        return ""
    if s[0] in "{[":
        try:
            return json.dumps(json.loads(s), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return s
    # light number clean
    t = s.replace(",", "").replace("，", "")
    if _NUM_RE.match(t):
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t or "0"
    return s


def main() -> None:
    tests = pd.read_excel(ROOT / "tests.xlsx")
    ids = [str(x) for x in tests["id"].tolist()]
    assert len(ids) == 908

    vl = load_ckpt(ROOT / "outputs" / "qwen3-vl" / "checkpoint.jsonl")
    flash = load_ckpt(ROOT / "outputs" / "qwen3.8-flash-0915" / "checkpoint.jsonl")
    maxa = load_ckpt(ROOT / "outputs" / "qwen3.8-max-0902" / "checkpoint.jsonl")
    split_retry = load_ckpt(ROOT / "outputs" / "qwen3.8-Max-split-retry" / "checkpoint.jsonl")

    split_ids = {
        x.strip()
        for x in (ROOT / "retry_split_ids.txt").read_text(encoding="utf-8").splitlines()
        if x.strip()
    }
    maj_ids = {
        x.strip()
        for x in (ROOT / "retry_majority_ids.txt").read_text(encoding="utf-8").splitlines()
        if x.strip()
    }

    # classify by three-way agreement on canon answers
    unanimous, majority, split = [], [], []
    vote_ans: dict[str, str] = {}  # R3 vote answer (majority or priority=max)
    for qid in ids:
        a, b, c = canon(vl.get(qid, "")), canon(flash.get(qid, "")), canon(maxa.get(qid, ""))
        raw = {
            "vl": vl.get(qid, ""),
            "flash": flash.get(qid, ""),
            "max": maxa.get(qid, ""),
        }
        cans = [a, b, c]
        ctr = Counter(cans)
        top_n = ctr.most_common(1)[0][1]
        if top_n == 3:
            unanimous.append(qid)
            # prefer flash raw among equals
            vote_ans[qid] = raw["flash"]
        elif top_n == 2:
            majority.append(qid)
            winner_canon = ctr.most_common(1)[0][0]
            # prefer flash raw if flash is in majority
            if b == winner_canon:
                vote_ans[qid] = raw["flash"]
            elif c == winner_canon:
                vote_ans[qid] = raw["max"]
            else:
                vote_ans[qid] = raw["vl"]
        else:
            split.append(qid)
            vote_ans[qid] = raw["max"]  # R3: split takes max

    # R4: same as R3 but overwrite split_retry ids with new max answers
    r4_ans = dict(vote_ans)
    for qid in split_ids:
        if qid in split_retry and str(split_retry[qid]).strip() != "":
            r4_ans[qid] = split_retry[qid]

    # Also load baseline_82 for reference (after language fixes)
    b82 = pd.read_excel(ROOT / "submissions" / "baseline_82.xlsx", dtype=str, keep_default_na=False)
    b82["id"] = b82["id"].astype(str)
    cur = dict(zip(b82["id"], b82["answer"]))

    lines = []
    lines.append(f"N=908")
    lines.append(f"ckpt sizes vl={len(vl)} flash={len(flash)} max={len(maxa)} split_retry={len(split_retry)}")
    lines.append(f"classified unanimous={len(unanimous)} majority={len(majority)} split={len(split)}")
    lines.append(f"file maj_ids={len(maj_ids)} split_ids={len(split_ids)}")
    lines.append(f"set overlap maj_file vs majority_class={len(maj_ids & set(majority))}")
    lines.append(f"set overlap split_file vs split_class={len(split_ids & set(split))}")
    lines.append(f"split_ids - split_class = {sorted(split_ids - set(split), key=int)[:30]} ... n={len(split_ids-set(split))}")
    lines.append(f"split_class - split_ids = {sorted(set(split)-split_ids, key=int)[:30]} ... n={len(set(split)-split_ids)}")

    # Coverage of answers in each round reconstruction
    def coverage(ansmap):
        return sum(1 for qid in ids if str(ansmap.get(qid, "")).strip() != "")

    lines.append(f"coverage R1(vl)={coverage(vl)} R2(flash)={coverage(flash)} R3(vote)={coverage(vote_ans)} R4={coverage(r4_ans)}")

    # Compare R3 vs R4 answer changes
    changed = []
    unchanged_in_split_file = []
    for qid in sorted(split_ids, key=int):
        old = canon(vote_ans.get(qid, ""))
        new = canon(r4_ans.get(qid, ""))
        if old != new:
            changed.append(qid)
        else:
            unchanged_in_split_file.append(qid)
    lines.append(f"\nR3->R4 among split_ids: changed={len(changed)} unchanged={len(unchanged_in_split_file)}")
    lines.append(f"score R3=718 R4=742  delta=+24")
    lines.append(
        "Interpretation: only the changed answers can explain +24. "
        f"Let G=# newly correct, L=# newly wrong among {len(changed)} flips; G-L=+24, G+L<= {len(changed)}."
    )
    # G-L=24, G+L<=n_changed, G,L>=0 => G=(n+24)/2 bounds
    n = len(changed)
    # G = ( (G+L) + (G-L) ) / 2 <= (n+24)/2, G >= 24
    lines.append(f"Bounds on newly-correct among changed: G >= 24, G <= {(n+24)//2 if n else 0}, and L=G-24")
    if n:
        # If we assume wrong->wrong doesn't happen often... still can't pin exact ids
        lines.append(
            f"If ALL flips that aren't net-loss are wrong->right and no right->wrong (L=0), then exactly G=24 of {n} flips are correct now and previously wrong; the other {n-24} flips are wrong->wrong."
        )
        lines.append(
            "Without L=0 assumption we CANNOT name which of the changed ids are correct—only that net +24."
        )

    # Unanimous correctness bound from R1
    # On unanimous ids, R1/R2/R3 all submit the same canon answer (by definition).
    U = len(unanimous)
    lines.append(f"\n=== Unanimous bound ===")
    lines.append(f"|U|={U}. On U, vl=flash=max (canon), so R1/R2/R3 contribute the SAME C(U) correct count.")
    lines.append(f"R1 total=494 => C(U) <= 494 => wrong_in_U >= {U - 494} (if U>=494 else 0)")
    lines.append(f"R2 total=699 => correct outside U = 699 - C(U) >= 699-494 = 205 (using max C(U))")
    lines.append(f"Also C(U) >= 494 - (908-U) = {494 - (908-U)}  (vl correct all outside U worst-case)")
    # tighter: outside U has 908-U questions; vl got 494 total
    # C(U) >= 494 - (908-U)
    lo = max(0, 494 - (908 - U))
    hi = min(U, 494)
    lines.append(f"Therefore C(U) in [{lo}, {hi}], wrong_in_U in [{U-hi}, {U-lo}]")

    # Majority: R3 uses majority answer. Compare flash vs vote on majority set.
    maj_flash_eq_vote = sum(1 for qid in majority if canon(flash.get(qid, "")) == canon(vote_ans[qid]))
    maj_flash_ne_vote = [qid for qid in majority if canon(flash.get(qid, "")) != canon(vote_ans[qid])]
    lines.append(f"\n=== Majority set ===")
    lines.append(f"|M|={len(majority)}; flash already equals vote on {maj_flash_eq_vote}; flash differs on {len(maj_flash_ne_vote)}")
    lines.append(f"R2->R3 delta = 718-699 = +19")
    lines.append(
        "R3 differs from pure-flash where: (a) majority picks non-flash, (b) split picks max != flash."
    )
    split_flash_ne = [qid for qid in split if canon(flash.get(qid, "")) != canon(vote_ans[qid])]
    lines.append(f"split where vote(max)!=flash: {len(split_flash_ne)}")
    lines.append(f"majority where vote!=flash: {len(maj_flash_ne_vote)}")
    # R2->R3 changes
    r2_to_r3_changed = [
        qid for qid in ids if canon(flash.get(qid, "")) != canon(vote_ans.get(qid, ""))
    ]
    lines.append(f"total R2(flash)->R3(vote) answer changes: {len(r2_to_r3_changed)}")
    lines.append(f"delta +19 on those {len(r2_to_r3_changed)} flips: same G-L=+19 logic; cannot name ids without L=0.")

    # What we CAN certify as correct under strong assumptions
    lines.append("\n=== What CAN be certified ===")
    lines.append(
        "1) From scores alone, individual ids outside U cannot be proven correct "
        "(only aggregate nets on flip sets)."
    )
    lines.append(
        "2) If we ASSUME unanimous-same-answer => still not all correct "
        f"(at least {max(0, U-494)} of U are wrong by R1 bound)."
    )
    lines.append(
        "3) Strong assumption L=0 on R3->R4 flips: exactly 24 of the changed split-retry ids "
        "became newly correct; the remaining changed are still wrong (wrong->wrong). "
        "Still unknown WHICH 24."
    )
    lines.append(
        "4) If an id's answer never changed across R1..R4 AND appears in all submissions, "
        "its correctness is locked to whether that shared answer is right—"
        "only U has that property for R1-R3; R1 score then bounds U."
    )

    # Intersection: answers that equal current baseline_82 and equal flash and were never flipped R3->R4
    # High-confidence "stable majority with flash" set
    stable_flash_majority = []
    for qid in majority:
        if canon(flash.get(qid, "")) == canon(vote_ans[qid]) == canon(cur.get(qid, "")):
            if qid not in changed:
                stable_flash_majority.append(qid)
    lines.append(f"\nStable majority(=flash=vote=baseline82, not in R4 flips): {len(stable_flash_majority)}")
    lines.append(
        "These are NOT proven correct—but they are the largest 'flash was already right-or-wrong "
        "and vote kept flash' block. R2's 699 includes C(U)+C(this block)+C(other flash-only)."
    )

    # Compute how many of R4/baseline answers match flash / max / vl
    match = Counter()
    for qid in ids:
        c = canon(cur.get(qid, ""))
        match["eq_flash"] += int(c == canon(flash.get(qid, "")))
        match["eq_max"] += int(c == canon(maxa.get(qid, "")) or c == canon(split_retry.get(qid, "")))
        match["eq_vl"] += int(c == canon(vl.get(qid, "")))
        match["eq_r4"] += int(c == canon(r4_ans.get(qid, "")))
    lines.append(f"\nbaseline82 vs models: {dict(match)}")

    # List R3->R4 changed ids for user
    lines.append(f"\n=== R3->R4 changed ids ({len(changed)}) ===")
    lines.append(",".join(changed))

    # Save changed id details
    rows = []
    for qid in changed:
        rows.append(
            {
                "id": qid,
                "r3": vote_ans.get(qid, ""),
                "r4": r4_ans.get(qid, ""),
                "flash": flash.get(qid, ""),
                "vl": vl.get(qid, ""),
                "max0": maxa.get(qid, ""),
                "in_split_class": qid in set(split),
                "in_maj_class": qid in set(majority),
                "in_uni_class": qid in set(unanimous),
            }
        )
    out_csv = ROOT / "submissions" / "r3_to_r4_changed.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")

    out = ROOT / "submissions" / "infer_correct_from_scores.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out.read_text(encoding="utf-8")[:4000])
    print("\n... wrote", out)
    print("wrote", out_csv)


if __name__ == "__main__":
    main()
