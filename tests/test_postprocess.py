from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from baseline.postprocess import normalize_answer


def test_structure_normalize():
    raw = """```json
    {
      "row_count": 4,
      "col_count": 3,
      "cells": [
        {"text": "项目", "row": 0, "col": 0, "rowspan": 2, "colspan": 1},
        {"text": "金额", "row": 0, "col": 1, "rowspan": 1, "colspan": 2}
      ]
    }
    ```"""
    out = normalize_answer(raw, "json", "structure")
    assert '"row_count":4' in out
    assert '"text":"项目"' in out


def test_number_normalize():
    assert normalize_answer("答案是 125,000", "number", "extract") == "125000"


def test_array_normalize():
    out = normalize_answer('[1, "销售额", "产品销售表"]', "json_array", "extract")
    assert out == '[1,"销售额","产品销售表"]'


if __name__ == "__main__":
    test_structure_normalize()
    test_number_normalize()
    test_array_normalize()
    print("postprocess ok")
