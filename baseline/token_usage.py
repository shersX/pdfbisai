from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "image_tokens")


def empty_usage_row(qid: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": qid,
        "from_cache": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "image_tokens": 0,
    }
    row.update(extra)
    return row


def usage_to_row(
    qid: str,
    usage: dict[str, Any] | None,
    *,
    from_cache: bool = False,
    model: str | None = None,
    file_name: str | None = None,
    question_type: str | None = None,
) -> dict[str, Any]:
    usage = usage or {}
    row = empty_usage_row(qid, from_cache=from_cache)
    if model is not None:
        row["model"] = model
    if file_name is not None:
        row["file_name"] = file_name
    if question_type is not None:
        row["question_type"] = question_type

    for key in TOKEN_FIELDS:
        val = usage.get(key)
        if val is None:
            continue
        try:
            row[key] = int(val)
        except (TypeError, ValueError):
            row[key] = 0

    # Some VL responses only return input/output; derive total if missing
    if not row["total_tokens"] and (row["input_tokens"] or row["output_tokens"]):
        row["total_tokens"] = int(row["input_tokens"]) + int(row["output_tokens"])

    # Keep extra detail fields for debugging without breaking the table
    details = {
        k: v
        for k, v in usage.items()
        if k not in TOKEN_FIELDS and v is not None
    }
    if details:
        row["usage_detail"] = json.dumps(details, ensure_ascii=False)
    return row


def load_usage_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        done[str(item["id"])] = item
    return done


def write_token_reports(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_xlsx = output_dir / "token_usage.xlsx"
    summary_json = output_dir / "token_usage_summary.json"

    df = pd.DataFrame(rows)
    preferred = [
        "id",
        "file_name",
        "question_type",
        "model",
        "from_cache",
        "input_tokens",
        "output_tokens",
        "image_tokens",
        "total_tokens",
        "usage_detail",
    ]
    cols = [c for c in preferred if c in df.columns] + [
        c for c in df.columns if c not in preferred
    ]
    if not df.empty:
        df = df[cols]
        try:
            df["id"] = df["id"].astype(int)
            df = df.sort_values("id")
        except Exception:  # noqa: BLE001
            pass
    df.to_excel(detail_xlsx, index=False)

    def _sum(col: str) -> int:
        if col not in df.columns or df.empty:
            return 0
        return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    summary = {
        "question_count": int(len(df)),
        "from_cache_count": int(df["from_cache"].fillna(False).astype(bool).sum())
        if "from_cache" in df.columns and not df.empty
        else 0,
        "input_tokens": _sum("input_tokens"),
        "output_tokens": _sum("output_tokens"),
        "image_tokens": _sum("image_tokens"),
        "total_tokens": _sum("total_tokens"),
        "avg_total_tokens": round(_sum("total_tokens") / len(df), 2) if len(df) else 0,
    }
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"detail_xlsx": detail_xlsx, "summary_json": summary_json}
