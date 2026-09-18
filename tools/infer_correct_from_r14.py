"""Score-based bounds using analysis_three_runs.xlsx buckets (一致497/多数285/分歧126)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def load_ckpt(path: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    if not path.exists():
        return done
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
    t = s.replace(",", "").replace("，", "")
    if _NUM_RE.match(t):
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t or "0"
    return s


def main() -> None:
    xls = pd.ExcelFile(ROOT / "analysis_three_runs.xlsx")
    # sheet names may be garbled; pick by shape
    sheets = {}
    for name in xls.sheet_names:
        df = pd.read_excel(xls, name)
        sheets[len(df)] = (name, df)

    uni_name, uni_df = sheets[497]
    # majority sheet is long-form 855 rows = 285*3
    maj_name, maj_df = sheets[855]
    spl_name, spl_df = sheets[378]  # 126*3

    uni_ids = set(uni_df["id"].astype(str))
    maj_ids = set(maj_df["id"].astype(str))
    spl_ids = set(spl_df["id"].astype(str))

    split_file = {
        x.strip()
        for x in (ROOT / "retry_split_ids.txt").read_text(encoding="utf-8").splitlines()
        if x.strip()
    }

    vl = load_ckpt(ROOT / "outputs" / "qwen3-vl" / "checkpoint.jsonl")
    flash = load_ckpt(ROOT / "outputs" / "qwen3.8-flash-0915" / "checkpoint.jsonl")
    maxa = load_ckpt(ROOT / "outputs" / "qwen3.8-max-0902" / "checkpoint.jsonl")
    retry = load_ckpt(ROOT / "outputs" / "qwen3.8-Max-split-retry" / "checkpoint.jsonl")

    tests = pd.read_excel(ROOT / "tests.xlsx")
    all_ids = [str(i) for i in tests["id"]]

    lines = []
    lines.append("Buckets from analysis_three_runs.xlsx:")
    lines.append(f"  一致 sheet={uni_name!r} n_ids={len(uni_ids)}")
    lines.append(f"  多数 sheet={maj_name!r} n_ids={len(maj_ids)}")
    lines.append(f"  分歧 sheet={spl_name!r} n_ids={len(spl_ids)}")
    lines.append(f"  union={len(uni_ids|maj_ids|spl_ids)} overlap_uni_maj={len(uni_ids&maj_ids)} uni_spl={len(uni_ids&spl_ids)} maj_spl={len(maj_ids&spl_ids)}")
    lines.append(f"  retry_split_ids={len(split_file)}  extra_vs_分歧126={sorted(split_file-spl_ids, key=int)}")

    # Verify 一致: vl==flash
    uni_mismatch = [i for i in uni_ids if canon(vl.get(i, "")) != canon(flash.get(i, ""))]
    lines.append(f"\n一致497中 vl_canon!=flash_canon: {len(uni_mismatch)}")

    # Score facts
    R1, R2, R3, R4 = 494, 699, 718, 742
    lines.append("\nScores: R1(vl)=494 R2(flash)=699 R3(vote)=718 R4(split-retry)=742")
    lines.append(f"delta R1->R2={R2-R1} R2->R3={R3-R2} R3->R4={R4-R3}")

    # Bound C(U): on U, R1 and R2 submit same answer (vl==flash)
    U = len(uni_ids)
    # C(U) <= R1 = 494
    # C(U) >= R1 - (908-U) = 494 - 411 = 83
    lo_u = R1 - (908 - U)
    hi_u = min(U, R1)
    lines.append(f"\n=== 对「一致{U}」的可判定结论 ===")
    lines.append(f"因 vl≡flash，R1 与 R2 在这 {U} 题上对错完全相同。")
    lines.append(f"C(U) ∈ [{lo_u}, {hi_u}]")
    lines.append(f"故一致集里至少有 {U - hi_u} 题是错的，至多有 {U - lo_u} 题是错的。")
    lines.append(f"即：一致497里至少 {U-hi_u} 题错（因为 R1 总分只有 494 < 497）。")
    lines.append("**不能**把 497 题全部当成正确。")

    # Outside U
    out_n = 908 - U
    # Correct outside U in R2: R2 - C(U) ∈ [R2-hi_u, R2-lo_u] = [699-494, 699-83] = [205, 616]
    lines.append(f"\n=== 一致以外 {out_n} 题（多数+分歧）===")
    lines.append(f"R2 在外集上的正确数 C2_out ∈ [{R2-hi_u}, {R2-lo_u}]")
    lines.append(f"R3 总分 718 => C3_out ∈ [{R3-hi_u}, {R3-lo_u}] （外集在 vote 下）")
    lines.append(f"R4 总分 742 => C4_out ∈ [{R4-hi_u}, {R4-lo_u}]")
    lines.append("区间太宽，单靠总分无法点名外集里哪些题对。")

    # R2->R3: reconstruct vote answers for maj/split
    # majority: 2 of 3 agree - use long form
    maj_wide = {}
    for qid, g in maj_df.groupby(maj_df["id"].astype(str)):
        ans = {}
        for _, r in g.iterrows():
            m = str(r["model"])
            ans[m] = str(r["answer"]) if pd.notna(r["answer"]) else ""
        maj_wide[qid] = ans

    spl_wide = {}
    for qid, g in spl_df.groupby(spl_df["id"].astype(str)):
        ans = {}
        for _, r in g.iterrows():
            m = str(r["model"])
            ans[m] = str(r["answer"]) if pd.notna(r["answer"]) else ""
        spl_wide[qid] = ans

    def pick_majority(ans: dict[str, str]) -> str:
        # map keys
        items = list(ans.values())
        cans = [canon(x) for x in items]
        from collections import Counter

        ctr = Counter(cans)
        win = ctr.most_common(1)[0][0]
        # prefer flash raw
        for k, v in ans.items():
            if "flash" in k and canon(v) == win:
                return v
        for k, v in ans.items():
            if canon(v) == win:
                return v
        return items[0] if items else ""

    # R3 answer map
    r3 = {}
    for qid in uni_ids:
        r3[qid] = flash.get(qid, "")  # == vl
    for qid, ans in maj_wide.items():
        r3[qid] = pick_majority(ans)
    for qid, ans in spl_wide.items():
        # take max
        for k, v in ans.items():
            if "max" in k.lower() or "Max" in k:
                r3[qid] = v
                break
        else:
            r3[qid] = maxa.get(qid, "")

    # R4
    r4 = dict(r3)
    for qid in split_file:
        if qid in retry and str(retry[qid]).strip():
            r4[qid] = retry[qid]

    changed = [qid for qid in sorted(split_file, key=int) if canon(r3.get(qid, "")) != canon(r4.get(qid, ""))]
    lines.append(f"\n=== R3→R4（仅 split 重跑合并）===")
    lines.append(f"retry 名单 {len(split_file)} 题中，答案真正变化 {len(changed)} 题，未变 {len(split_file)-len(changed)} 题")
    lines.append(f"总分 +24 全部来自这 {len(changed)} 次翻转：G-L=+24，0≤L，G+L≤{len(changed)}")
    lines.append(f"故 G∈[24, {(len(changed)+24)//2}]，L=G-24")
    lines.append("即：这批翻转里「新变对」至少 24 题、至多 "
                 f"{(len(changed)+24)//2} 题；**无法从分数点名是哪几题**。")
    lines.append(f"未变化的 {len(split_file)-len(changed)} 题：对错状态相对 R3 不变，分数不提供新信息。")

    # R2->R3 changes
    r2_r3 = [qid for qid in all_ids if canon(flash.get(qid, "")) != canon(r3.get(qid, ""))]
    lines.append(f"\n=== R2(flash)→R3(vote) ===")
    lines.append(f"答案变化 {len(r2_r3)} 题，总分 +19 => 同样只能得集合净增益，不能点名。")

    # Final answer for user
    lines.append("\n========== 直接回答 ==========")
    lines.append("Q: 除了497之外，能否判定哪些题也是对的？")
    lines.append("A: **不能点名到具体 id。** 1–4 次提交的分数只给出集合层面的净增减：")
    lines.append("  • 一致497：并非全对（至少错 3 题，因 R1=494<497）；上界全对几乎不可能被分数单独证明。")
    lines.append("  • 多数285 + 分歧126：R2 在外集大约对 205～616 题（随一致集对错而变），区间无用。")
    lines.append("  • R3→R4：58 题答案变了，净 +24；可知「这 58 里有一批变对了」，但不知道是哪 24+。")
    lines.append("若要点名，需要：逐题对照（人工/更强模型）或设计只改 1 题的探针（不划算）。")
    lines.append("可用的弱先验（非证明）：flash 与最终提交相同且未进 R4 翻转的题，继承 R2 的高分底座，")
    lines.append("错题更可能集中在「曾翻转过」或「三方分歧」集合。")

    # Save changed list
    out = ROOT / "submissions" / "infer_correct_from_scores.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    pd.DataFrame({"id": changed}).to_csv(
        ROOT / "submissions" / "r3_to_r4_changed_ids.txt", index=False, header=False
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
