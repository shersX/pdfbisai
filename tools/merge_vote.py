"""三方投票合并：一致题直接采用，分歧题按多数投票，三方全分歧时按模型优先级取。

用法:
    python tools/merge_vote.py \
        --ckpt outputs/qwen3.8-flash-0915/checkpoint.jsonl \
        --ckpt outputs/qwen3-vl/checkpoint.jsonl \
        --ckpt outputs/qwen3.8-max-0902/checkpoint.jsonl \
        --priority outputs/qwen3.8-max-0902/checkpoint.jsonl \
        --out submission.xlsx

规则:
1. 所有模型答案（规范化后）一致 -> 直接采用。
2. 出现多数派（>=2 票）-> 采用多数派答案（用该派中第一个非空原始答案）。
3. 全部分歧 -> 采用 --priority 指定 checkpoint 的答案；未指定则用第一个 --ckpt。
4. 空答案不参与投票；若全部为空则输出空。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
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
    s = ans.strip()
    if not s:
        return ""
    if s[0] in "{[":
        try:
            return json.dumps(json.loads(s), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:  # noqa: BLE001
            return s
    return s


def excel_answer(text: str) -> str:
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return '""'
    return text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", action="append", required=True, help="checkpoint.jsonl，可多次传入")
    p.add_argument("--priority", default=None, help="全分歧时优先采用的 checkpoint 路径")
    p.add_argument("--out", default="submission.xlsx")
    args = p.parse_args()

    ckpts = [load_checkpoint(Path(c)) for c in args.ckpt]
    names = [Path(c).parent.name for c in args.ckpt]
    prio_idx = 0
    if args.priority:
        prio_path = str(Path(args.priority))
        for i, c in enumerate(args.ckpt):
            if str(Path(c)) == prio_path:
                prio_idx = i
                break

    df = pd.read_excel(ROOT / "tests.xlsx")
    results: list[dict[str, str]] = []
    n_unanimous = n_majority = n_priority = n_empty = 0

    for _, row in df.iterrows():
        qid = str(row["id"])
        raw = [c.get(qid, "") for c in ckpts]
        keys = [canon(r) for r in raw]
        votes = Counter(k for k in keys if k != "")

        if not votes:
            answer = ""
            n_empty += 1
        else:
            top_key, top_n = votes.most_common(1)[0]
            if top_n >= 2:
                answer = next(r for r, k in zip(raw, keys) if k == top_key)
                if top_n == sum(1 for k in keys if k != "") and len(votes) == 1:
                    n_unanimous += 1
                else:
                    n_majority += 1
            else:
                # 全分歧：优先级模型答案，若其为空则取第一个非空
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

    print(f"模型: {names}（全分歧时优先: {names[prio_idx]}）")
    print(
        f"共 {len(out_df)} 题 | 全一致 {n_unanimous} | 多数投票 {n_majority} | "
        f"全分歧取优先 {n_priority} | 全空 {n_empty}"
    )
    print(f"已导出 -> {out_path}")


if __name__ == "__main__":
    main()
