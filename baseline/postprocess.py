from __future__ import annotations

import json
import re
from typing import Any


def normalize_answer(raw: str, answer_format: str | None, question_type: str | None) -> str:
    """Clean model output into competition submission string."""
    text = (raw or "").strip()
    if not text:
        return ""

    text = _strip_code_fence(text)
    text = _strip_answer_prefix(text)

    fmt = (answer_format or "").strip().lower()
    qt = (question_type or "").strip().lower()

    if fmt == "json" or qt == "structure":
        obj = _try_parse_json_object(text)
        if obj is None:
            return text
        return json.dumps(_normalize_structure(obj), ensure_ascii=False, separators=(",", ":"))

    if fmt == "json_array":
        arr = _try_parse_json_array(text)
        if arr is None:
            return text
        return json.dumps(_normalize_scalars(arr), ensure_ascii=False, separators=(",", ":"))

    if fmt == "number":
        num = _extract_number(text)
        return num if num is not None else text

    # string / default
    if text.startswith("[") and text.endswith("]"):
        arr = _try_parse_json_array(text)
        if arr is not None:
            return json.dumps(_normalize_scalars(arr), ensure_ascii=False, separators=(",", ":"))
    return _clean_scalar(text)


def _strip_code_fence(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text


def _strip_answer_prefix(text: str) -> str:
    return re.sub(
        r"^(根据表格可知|答案是|最终答案[:：]|答[:：]|Answer[:：])\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def _try_parse_json_array(text: str) -> list[Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, list) else None
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, list) else None
        except json.JSONDecodeError:
            return None


def _normalize_structure(obj: dict[str, Any]) -> dict[str, Any]:
    cells = obj.get("cells", [])
    norm_cells = []
    if isinstance(cells, list):
        for c in cells:
            if not isinstance(c, dict):
                continue
            norm_cells.append(
                {
                    "text": _clean_scalar(str(c.get("text", ""))),
                    "row": int(c.get("row", 0)),
                    "col": int(c.get("col", 0)),
                    "rowspan": int(c.get("rowspan", 1)),
                    "colspan": int(c.get("colspan", 1)),
                }
            )
    return {
        "row_count": int(obj.get("row_count", 0)),
        "col_count": int(obj.get("col_count", 0)),
        "cells": norm_cells,
    }


def _normalize_scalars(arr: list[Any]) -> list[Any]:
    """json_array 元素：数字保持数值类型（不加引号）；空为 \"\"；文本为字符串。"""
    out: list[Any] = []
    for x in arr:
        if x is None:
            out.append("")
        elif isinstance(x, bool):
            out.append(x)
        elif isinstance(x, int):
            out.append(x)
        elif isinstance(x, float):
            out.append(int(x) if x.is_integer() else x)
        else:
            s = _clean_scalar(str(x))
            if s == "":
                out.append("")
                continue
            # 纯数字字符串 -> 数值，避免 ["3.6"] 这种带引号
            if re.fullmatch(r"-?\d+", s):
                out.append(int(s))
            elif re.fullmatch(r"-?\d+\.\d+", s):
                f = float(s)
                out.append(int(f) if f.is_integer() else f)
            else:
                out.append(s)
    return out


def _maybe_int(x: int | float) -> int | float | str:
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, int):
        return x
    return _number_to_str(x)


def _number_to_str(x: float) -> str:
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s


def _extract_number(text: str) -> str | None:
    cleaned = text.replace(",", "").replace("，", "")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    return m.group(0)


def _clean_scalar(text: str) -> str:
    s = text.strip().strip('"').strip("'")
    s = re.sub(r"\s+", " ", s)
    # remove thousand separators for pure numeric-looking values
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    return s
