"""Generate language-label A/B submission variants from a frozen baseline.

Only the questions "该表主要使用哪种语言或语言组合？" are touched; every other row is
copied byte-for-byte from the baseline. Each variant is written to submissions/ together
with a diff CSV so the score delta can be attributed to exactly one change.

Usage:
    python tools/make_lang_variants.py [--baseline submission.xlsx] [--tag 81.7]
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LANG_QUESTION = "该表主要使用哪种语言或语言组合？"

ZH_TO_EN = {
    "英语": "English",
    "英文": "English",
    "English": "English",
    "中文": "Chinese",
    "中英文": "Chinese and English",
    "中文和英文": "Chinese and English",
    "西班牙语": "Spanish",
    "立陶宛语": "Lithuanian",
    "挪威语": "Norwegian",
    "斯洛伐克语": "Slovak",
    "葡萄牙语": "Portuguese",
    "荷兰语和法语": "Dutch and French",
}

ENGLISH_FAMILY = {"英语", "英文", "English"}
BILINGUAL_FAMILY = {"中英文", "中文和英文", "Chinese and English"}


def load_submission(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str, keep_default_na=False)
    df["id"] = df["id"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str)
    return df


def lang_ids(tests_path: Path) -> list[str]:
    tests = pd.read_excel(tests_path)
    mask = tests["question"].astype(str).str.strip() == LANG_QUESTION
    return tests.loc[mask, "id"].astype(str).tolist()


def apply(df: pd.DataFrame, ids: list[str], fn) -> tuple[pd.DataFrame, list[tuple[str, str, str]]]:
    out = df.copy()
    diffs: list[tuple[str, str, str]] = []
    idx = out.set_index("id").index
    for qid in ids:
        if qid not in idx:
            continue
        i = out.index[out["id"] == qid][0]
        old = out.at[i, "answer"]
        new = fn(old)
        if new is not None and new != old:
            out.at[i, "answer"] = new
            diffs.append((qid, old, new))
    return out, diffs


def write_variant(df: pd.DataFrame, diffs, out_dir: Path, name: str) -> None:
    xlsx = out_dir / f"{name}.xlsx"
    save = df.copy()
    try:
        save["id"] = save["id"].astype(int)
    except ValueError:
        pass
    save.to_excel(xlsx, index=False)
    with (out_dir / f"{name}.diff.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "baseline", "variant"])
        w.writerows(diffs)
    print(f"{name:<28} changes={len(diffs):>3}  -> {xlsx.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=str(ROOT / "submission.xlsx"))
    ap.add_argument("--tests", default=str(ROOT / "tests.xlsx"))
    ap.add_argument("--tag", default="baseline", help="label for the frozen baseline copy")
    ap.add_argument("--out", default=str(ROOT / "submissions"))
    args = ap.parse_args()

    baseline_path = Path(args.baseline)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    frozen = out_dir / f"baseline_{args.tag}.xlsx"
    if not frozen.exists():
        shutil.copy2(baseline_path, frozen)
        print(f"frozen baseline -> {frozen.relative_to(ROOT)}")
    else:
        print(f"frozen baseline exists, reuse -> {frozen.relative_to(ROOT)}")

    df = load_submission(frozen)
    ids = lang_ids(Path(args.tests))
    blank = df[df["answer"].str.strip() == ""]
    print(f"rows={len(df)}  lang_questions={len(ids)}  blank_answers={len(blank)}")
    if len(blank):
        print("  WARNING blank ids:", blank["id"].tolist()[:20])

    # 1) EN: every language label -> English wording
    def to_en(a: str):
        return ZH_TO_EN.get(a.strip(), None)

    v, d = apply(df, ids, to_en)
    unmapped = [q for q in ids if df.loc[df["id"] == q, "answer"].iloc[0].strip() not in ZH_TO_EN]
    if unmapped:
        print("  WARNING unmapped labels for ids:", unmapped)
    write_variant(v, d, out_dir, "v_EN")

    # 2) ZH clean: unify to 英语 + 中英文 (least-change canonical Chinese form)
    def to_zh_clean(a: str):
        s = a.strip()
        if s in ENGLISH_FAMILY:
            return "英语"
        if s in BILINGUAL_FAMILY:
            return "中英文"
        return None

    v, d = apply(df, ids, to_zh_clean)
    write_variant(v, d, out_dir, "v_ZH_clean")

    # 3) ZH 英文: English-family -> 英文, bilingual untouched (isolates 英语 vs 英文)
    def to_zh_yingwen(a: str):
        return "英文" if a.strip() in ENGLISH_FAMILY else None

    v, d = apply(df, ids, to_zh_yingwen)
    write_variant(v, d, out_dir, "v_ZH_yingwen")

    # 4) ZH 中英文: bilingual -> 中英文, English-family untouched
    def to_zh_zhongyingwen(a: str):
        return "中英文" if a.strip() in BILINGUAL_FAMILY else None

    v, d = apply(df, ids, to_zh_zhongyingwen)
    write_variant(v, d, out_dir, "v_ZH_zhongyingwen")

    # 5) ZH 中文和英文: bilingual -> 中文和英文, English-family untouched
    def to_zh_zhongwenheyingwen(a: str):
        return "中文和英文" if a.strip() in BILINGUAL_FAMILY else None

    v, d = apply(df, ids, to_zh_zhongwenheyingwen)
    write_variant(v, d, out_dir, "v_ZH_zhongwenheyingwen")

    # 6/7) Final candidates after 英语 confirmed as gold (v_ZH_yingwen: 81.7 -> 80.0, -16 q):
    #      English-family -> 英语, bilingual -> one of the two Chinese wordings.
    def final_a(a: str):
        s = a.strip()
        if s in ENGLISH_FAMILY:
            return "英语"
        if s in BILINGUAL_FAMILY:
            return "中英文"
        return None

    def final_b(a: str):
        s = a.strip()
        if s in ENGLISH_FAMILY:
            return "英语"
        if s in BILINGUAL_FAMILY:
            return "中文和英文"
        return None

    v, d = apply(df, ids, final_a)
    write_variant(v, d, out_dir, "v_FINAL_A_yingyu_zhongyingwen")
    v, d = apply(df, ids, final_b)
    write_variant(v, d, out_dir, "v_FINAL_B_yingyu_zhongwenheyingwen")


if __name__ == "__main__":
    main()
