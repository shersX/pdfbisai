"""生成两个模型答案不一致的题目 id 列表，供仲裁模型重跑。

用法:
    python tools/make_diff_ids.py \
        --a outputs/qwen3-vl/checkpoint.jsonl \
        --b outputs/qwen3.8-flash-0915/checkpoint.jsonl \
        --out diff_ids.txt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_checkpoint(path: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        done[str(item["id"])] = str(item.get("answer", "")).strip()
    return done


def canon(ans: str) -> str:
    """规范化后再比较，避免 JSON 空格差异造成假分歧。"""
    s = ans.strip()
    if not s:
        return ""
    if s[0] in "{[":
        try:
            return json.dumps(json.loads(s), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:  # noqa: BLE001
            return s
    return s


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--out", default="diff_ids.txt")
    args = p.parse_args()

    a = load_checkpoint(Path(args.a))
    b = load_checkpoint(Path(args.b))
    df = pd.read_excel(ROOT / "tests.xlsx")

    diff_ids: list[str] = []
    stats: dict[str, int] = {}
    for _, row in df.iterrows():
        qid = str(row["id"])
        if canon(a.get(qid, "")) != canon(b.get(qid, "")):
            diff_ids.append(qid)
            qt = str(row["question_type"])
            stats[qt] = stats.get(qt, 0) + 1

    out = Path(args.out)
    out.write_text("\n".join(diff_ids) + "\n", encoding="utf-8")
    print(f"分歧题 {len(diff_ids)} 道 -> {out}")
    print(f"按题型: {stats}")


if __name__ == "__main__":
    main()
