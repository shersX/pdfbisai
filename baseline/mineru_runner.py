"""多数与分歧 sheet 中 json_array：先 MinerU 解析落盘，再送大模型。"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from baseline.config import ROOT, Settings
from baseline.file_utils import resolve_file
from baseline.mineru_client import BATCH_LIMIT, MinerUClient, MinerUError
from baseline.postprocess import normalize_answer
from baseline.prompts import build_mineru_user_prompt, system_prompt_for
from baseline.qwen_client import QwenVLClient
from baseline.runner import _excel_answer, _load_answer_checkpoint
from baseline.token_usage import empty_usage_row, load_usage_checkpoint, usage_to_row


SHEET_NAME = "多数与分歧"


def resolve_tests_path(preferred: Path) -> Path:
    fallback = ROOT / "tests_maj_split.xlsx"
    for path in (preferred, fallback):
        if not path.exists():
            continue
        try:
            xl = pd.ExcelFile(path)
        except Exception:  # noqa: BLE001
            continue
        if SHEET_NAME in xl.sheet_names:
            return path
    raise FileNotFoundError(
        f"找不到含「{SHEET_NAME}」的题目表。请先生成 tests.xlsx 该 sheet，"
        f"或使用 {fallback.name}。"
    )


def load_json_array_queue(tests_path: Path) -> pd.DataFrame:
    path = resolve_tests_path(tests_path)
    df = pd.read_excel(path, sheet_name=SHEET_NAME, dtype=str, keep_default_na=False)
    required = {"id", "file_name", "question_type", "question", "answer_format"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} / {SHEET_NAME} 缺少字段: {sorted(missing)}")
    ja = df[df["answer_format"].astype(str).str.strip().str.lower() == "json_array"].copy()
    ja["id"] = ja["id"].astype(str).str.strip()
    print(f"题目表 {path.name} / {SHEET_NAME}: 共 {len(df)} 题，json_array {len(ja)} 题")
    return ja


def parsed_dir(settings: Settings, file_name: str) -> Path:
    return settings.cache_dir / "mineru" / "parsed" / file_name


def parsed_md_path(settings: Settings, file_name: str) -> Path:
    return parsed_dir(settings, file_name) / "full.md"


def parse_unique_files(
    settings: Settings,
    df: pd.DataFrame,
    *,
    resume: bool = True,
) -> dict[str, Path]:
    if not settings.mineru_token:
        raise MinerUError("未设置 MINERU_API_KEY。")

    names = sorted({str(x).strip() for x in df["file_name"] if str(x).strip()})
    client = MinerUClient(settings.mineru_token, settings.mineru_api_base)
    ready: dict[str, Path] = {}
    pending: list[str] = []

    for name in names:
        md = parsed_md_path(settings, name)
        if resume and md.exists() and md.stat().st_size > 0:
            ready[name] = md
        else:
            pending.append(name)

    print(
        f"MinerU 文件: 已缓存 {len(ready)}，待解析 {len(pending)}，"
        f"模型={settings.mineru_model_version}"
    )
    if not pending:
        return ready

    for i in range(0, len(pending), BATCH_LIMIT):
        chunk = pending[i : i + BATCH_LIMIT]
        paths = [resolve_file(settings.files_dir, name) for name in chunk]
        print(f"提交 MinerU 批次 {i // BATCH_LIMIT + 1}: {len(paths)} 个文件")
        batch_id = client.submit_local_files(
            paths,
            model_version=settings.mineru_model_version,
        )
        (settings.cache_dir / "mineru").mkdir(parents=True, exist_ok=True)
        results = client.poll_batch(batch_id)
        by_name = {str(item.get("file_name") or ""): item for item in results}

        for name in chunk:
            item = by_name.get(name) or by_name.get(Path(name).name)
            dest = parsed_dir(settings, name)
            dest.mkdir(parents=True, exist_ok=True)
            meta_path = dest / "meta.json"
            meta_path.write_text(json.dumps(item or {}, ensure_ascii=False, indent=2), encoding="utf-8")
            state = str((item or {}).get("state", "")).lower()
            if state != "done":
                err = (item or {}).get("err_msg") or f"state={state or 'missing'}"
                print(f"  解析失败 {name}: {err}")
                continue
            zip_url = (item or {}).get("full_zip_url")
            if not zip_url:
                print(f"  解析成功但无 zip: {name}")
                continue
            md = client.download_markdown(str(zip_url), dest)
            # 统一落到 dest/full.md，方便 resume
            target = dest / "full.md"
            if md.resolve() != target.resolve():
                target.write_text(md.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            ready[name] = target
            print(f"  已保存 {target.relative_to(settings.cache_dir)}")

    return ready


def _clip_markdown(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = max_chars * 3 // 4
    tail = max_chars - head
    return text[:head] + "\n\n…(中间已截断)…\n\n" + text[-tail:]


def run_mineru_pipeline(
    settings: Settings,
    *,
    limit: int | None = None,
    ids: list[int] | None = None,
    resume: bool = True,
    max_workers: int | None = None,
    parse_only: bool = False,
    llm_only: bool = False,
) -> Path | None:
    df = load_json_array_queue(settings.tests_path)
    if ids:
        id_set = {str(i) for i in ids}
        df = df[df["id"].isin(id_set)].copy()
    if limit is not None:
        df = df.head(limit).copy()

    out_dir = ROOT / "outputs" / f"mineru-{settings.mineru_llm_model}"
    mineru_settings = Settings(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.mineru_llm_model,
        files_dir=settings.files_dir,
        tests_path=settings.tests_path,
        output_dir=out_dir,
        cache_dir=settings.cache_dir,
        max_pdf_pages=settings.max_pdf_pages,
        pdf_zoom=settings.pdf_zoom,
        max_workers=settings.max_workers,
        mineru_token=settings.mineru_token,
        mineru_api_base=settings.mineru_api_base,
        mineru_model_version=settings.mineru_model_version,
        mineru_llm_model=settings.mineru_llm_model,
        mineru_md_max_chars=settings.mineru_md_max_chars,
    )
    mineru_settings.output_dir.mkdir(parents=True, exist_ok=True)
    mineru_settings.cache_dir.mkdir(parents=True, exist_ok=True)

    parsed: dict[str, Path] = {}
    if not llm_only:
        parsed = parse_unique_files(mineru_settings, df, resume=resume)
    else:
        for name in sorted({str(x) for x in df["file_name"]}):
            md = parsed_md_path(mineru_settings, name)
            if md.exists():
                parsed[name] = md
        print(f"--llm-only：复用已解析 Markdown {len(parsed)} 个文件")

    if parse_only:
        miss = sorted({str(x) for x in df["file_name"]} - set(parsed))
        print(f"parse-only 完成，成功 {len(parsed)}，缺失 {len(miss)}")
        if miss:
            print("缺失文件:", ", ".join(miss[:20]), ("…" if len(miss) > 20 else ""))
        return None

    return _solve_with_markdown(mineru_settings, df, parsed, resume=resume, max_workers=max_workers)


def _solve_with_markdown(
    settings: Settings,
    df: pd.DataFrame,
    parsed: dict[str, Path],
    *,
    resume: bool,
    max_workers: int | None,
) -> Path:
    workers = max(1, max_workers if max_workers is not None else settings.max_workers)
    client = QwenVLClient(
        api_key=settings.api_key,
        model=settings.mineru_llm_model,
        base_url=settings.base_url,
        cache_dir=settings.cache_dir / "llm_mineru",
    )

    checkpoint_path = settings.output_dir / "checkpoint.jsonl"
    usage_path = settings.output_dir / "token_usage.jsonl"
    errors_path = settings.output_dir / "errors.jsonl"
    write_lock = threading.Lock()
    done = _load_answer_checkpoint(checkpoint_path) if resume else {}

    pending: list[pd.Series] = []
    for _, row in df.iterrows():
        qid = str(row["id"])
        if resume and qid in done and str(done[qid]).strip() != "":
            continue
        pending.append(row)

    print(f"大模型 {settings.mineru_llm_model} 并发={workers}，待解={len(pending)}/{len(df)}")

    def _persist(qid: str, answer: str, usage_row: dict, error: str | None = None) -> None:
        with write_lock:
            with checkpoint_path.open("a", encoding="utf-8") as ckpt:
                ckpt.write(json.dumps({"id": qid, "answer": answer}, ensure_ascii=False) + "\n")
            with usage_path.open("a", encoding="utf-8") as usage_f:
                usage_f.write(json.dumps(usage_row, ensure_ascii=False) + "\n")
            if error:
                with errors_path.open("a", encoding="utf-8") as ef:
                    ef.write(json.dumps({"id": qid, "error": error}, ensure_ascii=False) + "\n")

    def _worker(row: pd.Series) -> tuple[str, str, dict, str | None]:
        qid = str(row["id"])
        usage_row = empty_usage_row(
            qid,
            model=settings.mineru_llm_model,
            file_name=str(row["file_name"]),
            question_type=str(row.get("question_type") or ""),
        )
        try:
            answer, usage_row = _solve_one(row, settings, client, parsed)
            return qid, answer, usage_row, None
        except Exception as e:  # noqa: BLE001
            return qid, "", usage_row, str(e)

    if pending:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, row) for row in pending]
            for fut in tqdm(as_completed(futures), total=len(futures), desc="mineru-llm"):
                qid, answer, usage_row, error = fut.result()
                _persist(qid, answer, usage_row, error)

    # 只导出本队列，不覆盖根目录 submission.xlsx
    return _export_queue(settings, df)


def _solve_one(
    row: pd.Series,
    settings: Settings,
    client: QwenVLClient,
    parsed: dict[str, Path],
) -> tuple[str, dict]:
    file_name = str(row["file_name"])
    question = str(row.get("question") or "")
    question_type = str(row.get("question_type") or "")
    table_hint = str(row["table_hint"]) if str(row.get("table_hint") or "").strip() else None
    answer_format = str(row.get("answer_format") or "json_array")

    md_path = parsed.get(file_name)
    if md_path is None or not md_path.exists():
        raise FileNotFoundError(f"没有 MinerU Markdown: {file_name}")
    markdown = _clip_markdown(
        md_path.read_text(encoding="utf-8", errors="replace"),
        settings.mineru_md_max_chars,
    )

    system_prompt = system_prompt_for(question_type, answer_format)
    user_prompt = build_mineru_user_prompt(
        question, question_type, table_hint, answer_format, markdown
    )
    cache_key = hashlib.md5(
        f"{settings.mineru_llm_model}|mineru|{file_name}|{question}|{markdown[:2000]}".encode("utf-8")
    ).hexdigest()

    result = client.ask(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        image_paths=[],
        cache_key=cache_key,
    )
    answer = normalize_answer(result.text, answer_format, question_type)
    usage_row = usage_to_row(
        str(row["id"]),
        result.usage,
        from_cache=result.from_cache,
        model=settings.mineru_llm_model,
        file_name=file_name,
        question_type=question_type,
    )
    return answer, usage_row


def _export_queue(settings: Settings, df: pd.DataFrame) -> Path:
    answers = _load_answer_checkpoint(settings.output_dir / "checkpoint.jsonl")
    usages = load_usage_checkpoint(settings.output_dir / "token_usage.jsonl")
    rows = []
    usage_rows = []
    for _, row in df.iterrows():
        qid = str(row["id"])
        rows.append({"id": qid, "answer": _excel_answer(answers.get(qid, ""))})
        if qid in usages:
            usage_rows.append(usages[qid])
        else:
            usage_rows.append(
                empty_usage_row(
                    qid,
                    from_cache=True,
                    model=settings.mineru_llm_model,
                    file_name=str(row["file_name"]),
                    question_type=str(row.get("question_type") or ""),
                )
            )

    out_df = pd.DataFrame(rows, columns=["id", "answer"])
    try:
        out_df["id"] = out_df["id"].astype(int)
        out_df = out_df.sort_values("id")
    except Exception:  # noqa: BLE001
        pass

    from baseline.token_usage import write_token_reports

    write_token_reports(usage_rows, settings.output_dir)
    out_path = settings.output_dir / "submission_json_array.xlsx"
    out_df.to_excel(out_path, index=False)
    answered = sum(1 for r in rows if r["answer"] != '""')
    print(
        f"MinerU 队列导出 {answered}/{len(rows)} -> {out_path} "
        f"（未覆盖根目录 submission.xlsx）"
    )
    return out_path
