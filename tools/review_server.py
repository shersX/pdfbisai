"""本地审核服务：静态前端 + questions/decisions API。

用法:
    python tools/build_review_data.py   # 若 data.json 不存在
    python tools/review_server.py
    # 浏览器打开 http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "review"
DATA_PATH = REVIEW_DIR / "data.json"
DECISIONS_PATH = ROOT / "outputs" / "review_decisions.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {args[0] if args else fmt}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/questions":
            if not DATA_PATH.exists():
                self._send_json(404, {"error": "review/data.json 不存在，请先运行 tools/build_review_data.py"})
                return
            data = _read_json(DATA_PATH, {})
            self._send_json(200, data)
            return
        if path == "/api/decisions":
            self._send_json(200, _read_json(DECISIONS_PATH, {}))
            return
        if path in ("/", "/index.html"):
            self._serve_file(REVIEW_DIR / "index.html")
            return
        # static under review/
        rel = path.lstrip("/")
        candidate = (REVIEW_DIR / rel).resolve()
        if not str(candidate).startswith(str(REVIEW_DIR.resolve())):
            self._send_json(403, {"error": "forbidden"})
            return
        if candidate.is_file():
            self._serve_file(candidate)
            return
        self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/decisions":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        qid = str(payload.get("id", "")).strip()
        choice = str(payload.get("choice", "")).strip()
        if not qid or choice not in {"vl", "flash", "max"}:
            self._send_json(400, {"error": "需要 id 与 choice in vl|flash|max"})
            return

        data = _read_json(DATA_PATH, {"questions": []})
        question = next((q for q in data.get("questions", []) if str(q.get("id")) == qid), None)
        if question is None:
            self._send_json(404, {"error": f"题目不存在: {qid}"})
            return

        ans = question.get("answers", {}).get(choice, {})
        decisions = _read_json(DECISIONS_PATH, {})
        decisions[qid] = {
            "choice": choice,
            "model": ans.get("model", choice),
            "answer": ans.get("answer", ""),
            "bucket": question.get("bucket"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(DECISIONS_PATH, decisions)
        self._send_json(200, {"ok": True, "id": qid, "decision": decisions[qid]})

    def _serve_file(self, path: Path) -> None:
        if not path.exists():
            self._send_json(404, {"error": f"missing {path.name}"})
            return
        ctype, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif path.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        else:
            ctype = ctype or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    if not DATA_PATH.exists():
        print("未找到 review/data.json，正在生成…")
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from build_review_data import build_questions

        questions = build_questions(ROOT / "analysis_three_runs.xlsx")
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(
            json.dumps(
                {
                    "version": 1,
                    "source": "analysis_three_runs.xlsx",
                    "count": len(questions),
                    "questions": questions,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"已生成 {DATA_PATH} ({len(questions)} 题)")

    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DECISIONS_PATH.exists():
        _write_json(DECISIONS_PATH, {})

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"审核前端: http://{args.host}:{args.port}")
    print(f"题目数据: {DATA_PATH}")
    print(f"判定落盘: {DECISIONS_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
