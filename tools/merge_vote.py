"""三方投票合并：一致题直接采用，分歧题按多数投票，三方全分歧时按模型优先级取。

数值会做等价归一（如 160112139.83 与 160112139.8300000131 视为相同），
多数派内优先采用更干净的写法（默认偏好 flash）。

用法:
    python tools/merge_vote.py \
        --ckpt outputs/qwen3.8-flash-0915/checkpoint.jsonl \
        --ckpt outputs/qwen3-vl/checkpoint.jsonl \
        --ckpt outputs/qwen3.8-max-0902/checkpoint.jsonl \
        --priority outputs/qwen3.8-max-0902/checkpoint.jsonl \
        --prefer-clean qwen3.8-flash-0915 \
        --out submission.xlsx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def load_checkpoint(path: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        done[str(item["id"])] = str(item.get("answer", "")).strip()
    return done


def strip_thousands(s: str) -> str:
    return s.replace(",", "").replace("，", "").strip()


def clean_number_string(s: str) -> str:
    s = strip_thousands(s)
    if not _NUM_RE.match(s):
        return s
    if "e" in s.lower():
        try:
            s = format(Decimal(s), "f")
        except InvalidOperation:
            return s
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def as_float(s: str) -> float | None:
    try:
        return float(strip_thousands(str(s)))
    except (TypeError, ValueError):
        return None


def scalars_equal(a, b, rel: float = 1e-9, abs_tol: float = 1e-6) -> bool:
    sa, sb = str(a).strip(), str(b).strip()
    if clean_number_string(sa) == clean_number_string(sb):
        return True
    fa, fb = as_float(sa), as_float(sb)
    if fa is None or fb is None:
        return sa == sb
    if fa == fb:
        return True
    scale = max(1.0, abs(fa), abs(fb))
    return abs(fa - fb) <= max(abs_tol, rel * scale)


def values_equal(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(values_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(values_equal(x, y) for x, y in zip(a, b))
    return scalars_equal(a, b)


def parse_answer(ans: str):
    s = ans.strip()
    if not s:
        return ""
    if s[0] in "{[":
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return s
    return s


def answers_equivalent(a: str, b: str) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return values_equal(parse_answer(a), parse_answer(b))


def cleanliness_score(ans: str) -> tuple:
    s = ans.strip()
    junk = len(re.findall(r"0{4,}", s))
    return (junk, len(s), s)


def pick_cleanest(candidates: list[str], prefer_raw: str | None = None) -> str:
    nonempty = [c for c in candidates if c.strip()]
    if not nonempty:
        return ""
    if prefer_raw and prefer_raw.strip():
        for c in nonempty:
            if answers_equivalent(c, prefer_raw):
                # if prefer model answer is in this cluster, use prefer's exact text if present
                pass
        if any(answers_equivalent(c, prefer_raw) for c in nonempty):
            # prefer exact prefer_raw if it's in candidates
            if prefer_raw in nonempty:
                return prefer_raw
            # else prefer any equivalent then cleanest among cluster
            cluster = [c for c in nonempty if answers_equivalent(c, prefer_raw)]
            return min(cluster, key=cleanliness_score)
    return min(nonempty, key=cleanliness_score)


def cluster_answers(raws: list[str]) -> list[list[int]]:
    """Return clusters as lists of indices into raws."""
    clusters: list[list[int]] = []
    for i, r in enumerate(raws):
        if not r.strip():
            continue
        placed = False
        for cluster in clusters:
            if answers_equivalent(raws[cluster[0]], r):
                cluster.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
    return clusters


def excel_answer(text: str) -> str:
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return '""'
    return text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", action="append", required=True, help="checkpoint.jsonl，可多次传入")
    p.add_argument("--priority", default=None, help="全分歧时优先采用的 checkpoint 路径")
    p.add_argument(
        "--prefer-clean",
        default=None,
        help="数值等价时优先采用该 checkpoint 的原文（如 flash 目录路径）",
    )
    p.add_argument("--out", default="submission.xlsx")
    args = p.parse_args()

    ckpt_paths = [Path(c) for c in args.ckpt]
    ckpts = [load_checkpoint(p) for p in ckpt_paths]
    names = [p.parent.name for p in ckpt_paths]

    prio_idx = 0
    if args.priority:
        prio_path = Path(args.priority)
        for i, c in enumerate(ckpt_paths):
            if c.resolve() == prio_path.resolve() or str(c) == str(prio_path):
                prio_idx = i
                break

    prefer_idx = None
    if args.prefer_clean:
        prefer_path = Path(args.prefer_clean)
        for i, c in enumerate(ckpt_paths):
            if c.resolve() == prefer_path.resolve() or str(c) == str(prefer_path) or c.parent.name == prefer_path.name:
                prefer_idx = i
                break

    df = pd.read_excel(ROOT / "tests.xlsx")
    results: list[dict[str, str]] = []
    n_unanimous = n_majority = n_priority = n_empty = n_format_merged = 0

    for _, row in df.iterrows():
        qid = str(row["id"])
        raw = [c.get(qid, "") for c in ckpts]
        clusters = cluster_answers(raw)

        if not clusters:
            answer = ""
            n_empty += 1
        else:
            clusters.sort(key=len, reverse=True)
            top = clusters[0]
            prefer_raw = raw[prefer_idx] if prefer_idx is not None else None

            if len(clusters) == 1:
                # 全员数值等价（含纯字符串一致）
                answer = pick_cleanest([raw[i] for i in top], prefer_raw=prefer_raw)
                # 区分：字符串原本就全一致 vs 格式合并
                strict = {json.dumps(parse_answer(raw[i]), ensure_ascii=False, sort_keys=True) if str(raw[i]).strip()[:1] in "{[" else raw[i].strip() for i in top}
                # simpler string equality check
                if len({raw[i].strip() for i in top}) == 1:
                    n_unanimous += 1
                else:
                    n_unanimous += 1
                    n_format_merged += 1
            elif len(top) >= 2:
                answer = pick_cleanest([raw[i] for i in top], prefer_raw=prefer_raw)
                n_majority += 1
            else:
                answer = raw[prio_idx] or next((r for r in raw if r), "")
                n_priority += 1

        results.append({"id": qid, "answer": excel_answer(answer)})

    out_df = pd.DataFrame(results, columns=["id", "answer"])
    try:
        out_df["id"] = out_df["id"].astype(int)
    except Exception:  # noqa: BLE001
        pass
    out_path = Path(args.out)
    out_df.to_excel(out_path, index=False)

    print(f"模型: {names}（全分歧优先: {names[prio_idx]}；干净写法偏好: {names[prefer_idx] if prefer_idx is not None else '最短'}）")
    print(
        f"共 {len(out_df)} 题 | 一致(含格式合并) {n_unanimous} | 其中格式合并 {n_format_merged} | "
        f"多数 {n_majority} | 全分歧取优先 {n_priority} | 全空 {n_empty}"
    )
    print(f"已导出 -> {out_path}")


if __name__ == "__main__":
    main()
