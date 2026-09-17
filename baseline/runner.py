from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from baseline.config import Settings
from baseline.file_utils import load_media_as_image_paths, resolve_file
from baseline.postprocess import normalize_answer
from baseline.prompts import build_user_prompt, system_prompt_for
from baseline.qwen_client import QwenVLClient
from baseline.token_usage import (
    empty_usage_row,
    load_usage_checkpoint,
    usage_to_row,
    write_token_reports,
)


VALID_TYPES = {"structure", "extract", "thinking"}


def load_tests(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    required = {"id", "file_name", "question_type", "question"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"tests.xlsx 缺少字段: {sorted(missing)}")

    mask = ~df["question_type"].astype(str).isin(VALID_TYPES)
    if mask.any():
        df.loc[mask, "question_type"] = df.loc[mask].apply(_infer_type, axis=1)
    return df


def _infer_type(row: pd.Series) -> str:
    fmt = str(row.get("answer_format", "")).lower()
    if fmt == "json":
        return "structure"
    q = str(row.get("question", ""))
    if any(k in q for k in ("计算", "多少", "合计", "分别", "增长", "占比")):
        return "thinking"
    return "extract"


def run_baseline(
    settings: Settings,
    *,
    limit: int | None = None,
    ids: list[int] | None = None,
    resume: bool = True,
    max_workers: int | None = None,
) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)

    workers = max(1, max_workers if max_workers is not None else settings.max_workers)

    full_df = load_tests(settings.tests_path)
    df = full_df
    if ids:
        id_set = set(ids)
        df = full_df[full_df["id"].isin(id_set)].copy()
    if limit is not None:
        df = df.head(limit).copy()

    client = QwenVLClient(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        cache_dir=settings.cache_dir / "llm",
    )

    checkpoint_path = settings.output_dir / "checkpoint.jsonl"
    usage_path = settings.output_dir / "token_usage.jsonl"
    errors_path = settings.output_dir / "errors.jsonl"
    write_lock = threading.Lock()

    done = _load_answer_checkpoint(checkpoint_path) if resume else {}
    usage_done = load_usage_checkpoint(usage_path) if resume else {}

    pending_rows: list[pd.Series] = []
    for _, row in df.iterrows():
        qid = str(row["id"])
        # Resume skips only non-empty answers; empty failures can be retried.
        if resume and qid in done and str(done[qid]).strip() != "":
            continue
        pending_rows.append(row)

    print(
        f"并发数={workers}，本批待解={len(pending_rows)}，"
        f"本批范围={len(df)}，全量题目={len(full_df)}"
    )

    def _persist(qid: str, answer: str, usage_row: dict, error: str | None = None) -> None:
        with write_lock:
            with checkpoint_path.open("a", encoding="utf-8") as ckpt:
                ckpt.write(json.dumps({"id": qid, "answer": answer}, ensure_ascii=False) + "\n")
            with usage_path.open("a", encoding="utf-8") as usage_f:
                usage_f.write(json.dumps(usage_row, ensure_ascii=False) + "\n")
            if error:
                with errors_path.open("a", encoding="utf-8") as ef:
                    ef.write(
                        json.dumps({"id": qid, "error": error}, ensure_ascii=False) + "\n"
                    )

    def _worker(row: pd.Series) -> tuple[str, str, dict, str | None]:
        qid = str(row["id"])
        usage_row = empty_usage_row(
            qid,
            model=settings.model,
            file_name=str(row["file_name"]),
            question_type=""
            if pd.isna(row["question_type"])
            else str(row["question_type"]),
        )
        try:
            answer, usage_row = _solve_one(row, settings, client)
            return qid, answer, usage_row, None
        except Exception as e:  # noqa: BLE001
            return qid, "", usage_row, str(e)

    if pending_rows:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, row) for row in pending_rows]
            for fut in tqdm(as_completed(futures), total=len(futures), desc="solving"):
                qid, answer, usage_row, error = fut.result()
                _persist(qid, answer, usage_row, error)

    # Always export the FULL test set from append-only jsonl (last write wins).
    # --ids/--limit only control which questions are solved in this run.
    return _export_from_checkpoints(settings, full_df)


def _load_answer_checkpoint(path: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        done[str(item["id"])] = item.get("answer", "")
    return done


def _excel_answer(answer: object) -> str:
    """Write a real empty-string token into Excel instead of a blank cell."""
    if answer is None or (isinstance(answer, float) and pd.isna(answer)):
        return '""'
    text = str(answer).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return '""'
    return text


def _export_from_checkpoints(settings: Settings, full_df: pd.DataFrame) -> Path:
    checkpoint_path = settings.output_dir / "checkpoint.jsonl"
    usage_path = settings.output_dir / "token_usage.jsonl"

    answers = _load_answer_checkpoint(checkpoint_path)
    usages = load_usage_checkpoint(usage_path)

    results: list[dict[str, str]] = []
    usage_rows: list[dict] = []
    for _, row in full_df.iterrows():
        qid = str(row["id"])
        results.append({"id": qid, "answer": _excel_answer(answers.get(qid, ""))})
        if qid in usages:
            usage_rows.append(usages[qid])
        else:
            usage_rows.append(
                empty_usage_row(
                    qid,
                    from_cache=True,
                    model=settings.model,
                    file_name=str(row["file_name"]),
                    question_type=""
                    if pd.isna(row["question_type"])
                    else str(row["question_type"]),
                )
            )

    out_df = pd.DataFrame(results, columns=["id", "answer"])
    try:
        out_df["id"] = out_df["id"].astype(int)
    except Exception:  # noqa: BLE001
        pass

    submission_path = settings.output_dir / "submission.xlsx"
    out_df.to_excel(submission_path, index=False)
    # 仅当本模型 checkpoint 基本覆盖全量题目时才同步到根目录，
    # 避免部分重跑（如仅跑分歧题）把根目录提交文件覆盖成空答案。
    answered = sum(1 for r in results if r["answer"] != '""')
    if answered >= 0.95 * len(results):
        out_df.to_excel(settings.tests_path.parent / "submission.xlsx", index=False)
    else:
        print(
            f"注意: 本次仅有 {answered}/{len(results)} 题有答案，"
            "未覆盖根目录 submission.xlsx（请用 tools/merge_vote.py 合并生成最终提交）"
        )

    reports = write_token_reports(usage_rows, settings.output_dir)
    print(
        f"已导出全量 {len(out_df)} 题 -> {submission_path.name}; "
        f"Token: {reports['detail_xlsx'].name}, {reports['summary_json'].name}"
    )
    return submission_path


def _solve_one(row: pd.Series, settings: Settings, client: QwenVLClient) -> tuple[str, dict]:
    file_name = str(row["file_name"])
    question = "" if pd.isna(row["question"]) else str(row["question"])
    question_type = "" if pd.isna(row["question_type"]) else str(row["question_type"])
    table_hint = None if pd.isna(row.get("table_hint")) else str(row.get("table_hint"))
    answer_format = None if pd.isna(row.get("answer_format")) else str(row.get("answer_format"))

    file_path = resolve_file(settings.files_dir, file_name)
    images = load_media_as_image_paths(
        file_path,
        settings.cache_dir,
        settings.max_pdf_pages,
        settings.pdf_zoom,
    )

    system_prompt = system_prompt_for(question_type, answer_format)
    user_prompt = build_user_prompt(question, question_type, table_hint, answer_format)

    cache_key = hashlib.md5(
        (
            f"{settings.model}|{file_name}|{question_type}|{question}|"
            f"{table_hint}|{answer_format}|{[p.name for p in images]}"
        ).encode("utf-8")
    ).hexdigest()

    result = client.ask(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        image_paths=images,
        cache_key=cache_key,
    )
    answer = normalize_answer(result.text, answer_format, question_type)
    usage_row = usage_to_row(
        str(row["id"]),
        result.usage,
        from_cache=result.from_cache,
        model=settings.model,
        file_name=file_name,
        question_type=question_type,
    )
    return answer, usage_row
