"""审核多数票（2:1）题：把「仅数字格式差」与「真内容差」分开。

问题示例：
  flash: ["160112139.83","180032578.58"]
  plus/max: ["160112139.8300000131","180032578.5800000131"]
字符串投票会让 plus+max 压过 flash，但实质是同一数字。

用法:
  python tools/review_majority.py
  python tools/review_majority.py --out majority_review.xlsx

输出 sheet:
  格式差可自动合并  — 归一化后三方一致，建议直接采用「最干净」答案
  真分歧待人工      — 归一化后仍 2:1，需要对照原图
  汇总              — 统计
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

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
    """去掉千分位与无意义尾零，不经 float，避免引入二进制噪声。"""
    s = strip_thousands(s)
    if not _NUM_RE.match(s):
        return s
    if "e" in s.lower():
        try:
            d = Decimal(s)
            s = format(d, "f")
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
    if a is None and b is None:
        return True
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
    if type(a) is not type(b) and not (
        isinstance(a, (int, float, str)) and isinstance(b, (int, float, str))
    ):
        # list vs list handled below; mixed scalar ok
        pass
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
    """越小越干净：优先短、少尾零、无二进制碎屑。"""
    s = ans.strip()
    junk = len(re.findall(r"0{4,}", s))
    return (junk, len(s), s)


def pick_cleanest(raws: list[str], model_names: list[str], prefer: str = "qwen3.8-flash") -> str:
    nonempty = [(m, r) for m, r in zip(model_names, raws) if r.strip()]
    if not nonempty:
        return ""
    # among equivalent cluster of prefer model first
    for m, r in nonempty:
        if m == prefer:
            return r
    return min((r for _, r in nonempty), key=cleanliness_score)


def classify_old_majority(
    raws: list[str],
) -> str | None:
    """Return unanimous|majority|split under strict string canon (old)."""

    def canon(ans: str) -> str:
        s = ans.strip()
        if not s:
            return ""
        if s[0] in "{[":
            try:
                return json.dumps(
                    json.loads(s), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            except Exception:  # noqa: BLE001
                return s
        return s

    keys = [canon(r) for r in raws]
    votes = Counter(k for k in keys if k)
    if not votes:
        return None
    top_n = votes.most_common(1)[0][1]
    n_nonempty = sum(1 for k in keys if k)
    if top_n >= 2:
        if top_n == n_nonempty and len(votes) == 1:
            return "unanimous"
        return "majority"
    return "split"


def cluster_by_equivalence(raws: list[str], models: list[str]) -> list[list[tuple[str, str]]]:
    clusters: list[list[tuple[str, str]]] = []
    for m, r in zip(models, raws):
        if not r.strip():
            continue
        placed = False
        for cluster in clusters:
            if answers_equivalent(cluster[0][1], r):
                cluster.append((m, r))
                placed = True
                break
        if not placed:
            clusters.append([(m, r)])
    return clusters


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="majority_review.xlsx")
    p.add_argument("--prefer", default="qwen3.8-flash", help="格式相同时优先采用的模型")
    args = p.parse_args()

    models = [
        ("qwen3-vl-plus", ROOT / "outputs/qwen3-vl/checkpoint.jsonl"),
        ("qwen3.8-flash", ROOT / "outputs/qwen3.8-flash-0915/checkpoint.jsonl"),
        ("qwen3.8-max-0902", ROOT / "outputs/qwen3.8-max-0902/checkpoint.jsonl"),
    ]
    ckpts = [(name, load_checkpoint(path)) for name, path in models]
    model_names = [n for n, _ in ckpts]
    maps = [m for _, m in ckpts]

    df = pd.read_excel(ROOT / "tests.xlsx")
    fmt_rows: list[dict] = []
    real_rows: list[dict] = []
    summary = {"old_majority": 0, "format_only": 0, "real_majority": 0}

    for _, row in df.iterrows():
        qid = str(row["id"])
        raws = [m.get(qid, "") for m in maps]
        if classify_old_majority(raws) != "majority":
            continue
        summary["old_majority"] += 1

        clusters = cluster_by_equivalence(raws, model_names)
        base = {
            "id": int(row["id"]) if str(row["id"]).isdigit() else row["id"],
            "file_name": row["file_name"],
            "question_type": row["question_type"],
            "question": row["question"],
        }

        if len(clusters) == 1:
            # 归一化后实质全一致
            summary["format_only"] += 1
            suggested = pick_cleanest(raws, model_names, prefer=args.prefer)
            for m, r in zip(model_names, raws):
                fmt_rows.append(
                    {
                        **base,
                        "model": m,
                        "answer": r,
                        "suggested_answer": suggested,
                        "reason": "数值/JSON 规范化后等价；建议用最干净写法",
                    }
                )
        else:
            summary["real_majority"] += 1
            # mark which side wins under string vote vs value vote
            sizes = sorted(((len(c), c) for c in clusters), key=lambda x: -x[0])
            majority_models = ",".join(m for m, _ in sizes[0][1])
            minority_models = ",".join(m for m, _ in sizes[1][1]) if len(sizes) > 1 else ""
            for m, r in zip(model_names, raws):
                real_rows.append(
                    {
                        **base,
                        "model": m,
                        "answer": r,
                        "value_majority_models": majority_models,
                        "value_minority_models": minority_models,
                        "cluster_size": next(len(c) for c in clusters if any(mm == m for mm, _ in c)),
                    }
                )

    out = Path(args.out)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(fmt_rows).to_excel(writer, sheet_name="格式差可自动合并", index=False)
        pd.DataFrame(real_rows).to_excel(writer, sheet_name="真分歧待人工", index=False)
        pd.DataFrame(
            [
                {"item": "旧规则多数票题数", "value": summary["old_majority"]},
                {"item": "仅格式差（可自动）", "value": summary["format_only"]},
                {"item": "真内容 2:1（需人工/强模型）", "value": summary["real_majority"]},
                {
                    "item": "人工量下降",
                    "value": f"{summary['format_only']}/{summary['old_majority']}",
                },
            ]
        ).to_excel(writer, sheet_name="汇总", index=False)

    print(
        f"旧多数 {summary['old_majority']} | 格式差 {summary['format_only']} | "
        f"真分歧 {summary['real_majority']} -> {out}"
    )


if __name__ == "__main__":
    main()
