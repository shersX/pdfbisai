from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import dashscope
from dashscope import MultiModalConversation


@dataclass
class AskResult:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    from_cache: bool = False


class QwenVLClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        cache_dir: Path | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
        self.cache_dir = cache_dir
        self._cache_lock = threading.Lock()
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        dashscope.api_key = api_key
        dashscope.base_http_api_url = self.base_url

    def _cache_path(self, cache_key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"{cache_key}.json"

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path],
        cache_key: str | None = None,
        max_retries: int = 3,
    ) -> AskResult:
        if cache_key:
            cp = self._cache_path(cache_key)
            with self._cache_lock:
                if cp and cp.exists():
                    data = json.loads(cp.read_text(encoding="utf-8"))
                    return AskResult(
                        text=data.get("text", ""),
                        usage=dict(data.get("usage") or {}),
                        from_cache=True,
                    )

        content = [{"text": user_prompt}]
        for p in image_paths:
            content.append({"image": f"file://{p.resolve().as_posix()}"})

        messages = [
            {"role": "system", "content": [{"text": system_prompt}]},
            {"role": "user", "content": content},
        ]

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = MultiModalConversation.call(
                    model=self.model,
                    messages=messages,
                    api_key=self.api_key,
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"DashScope error status={resp.status_code} "
                        f"code={getattr(resp, 'code', None)} "
                        f"message={getattr(resp, 'message', None)}"
                    )
                text = _extract_text(resp)
                usage = _extract_usage(resp)
                if cache_key:
                    cp = self._cache_path(cache_key)
                    if cp:
                        with self._cache_lock:
                            cp.write_text(
                                json.dumps(
                                    {"text": text, "usage": usage},
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                                encoding="utf-8",
                            )
                return AskResult(text=text, usage=usage, from_cache=False)
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"调用千问失败: {last_err}")


def _extract_text(resp) -> str:
    output = getattr(resp, "output", None)
    if not output:
        return ""
    choices = output.get("choices") if isinstance(output, dict) else getattr(output, "choices", None)
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else choices[0].message
    content = message.get("content") if isinstance(message, dict) else message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts).strip()
    return str(content).strip()


def _extract_usage(resp) -> dict[str, Any]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "items"):
        try:
            return dict(usage.items())
        except Exception:  # noqa: BLE001
            pass
    # DashScope Usage object often supports attribute access / __dict__
    data: dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "image_tokens",
        "input_tokens_details",
        "output_tokens_details",
        "prompt_tokens_details",
    ):
        if hasattr(usage, key):
            val = getattr(usage, key)
            if val is not None:
                data[key] = val
    if data:
        return data
    try:
        return asdict(usage)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {"raw": str(usage)}
