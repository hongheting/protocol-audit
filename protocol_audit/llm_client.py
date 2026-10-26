"""Unified LLM client for ProtocolAudit. Real calls only; logs every invocation."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = ROOT / "logs" / "llm"
SHANGHAI = timezone(timedelta(hours=8))

# Optional dotenv / key files (override with env vars; never commit real keys).
_SECRETS = {
    "glm": Path(
        os.environ.get(
            "BIGMODEL_CODING_ENV_FILE",
            str(Path.home() / ".config" / "protocol-audit" / "bigmodel-coding.env"),
        )
    ),
    "gemini": Path(
        os.environ.get(
            "GEMINI_API_KEY_FILE",
            str(Path.home() / ".config" / "protocol-audit" / "gemini-api-key.txt"),
        )
    ),
}


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _glm_key() -> str | None:
    _load_dotenv(_SECRETS["glm"])
    return os.environ.get("BIGMODEL_CODING_API_KEY") or os.environ.get("ZHIPU_API_KEY")


def _gemini_key() -> str | None:
    p = _SECRETS["gemini"]
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def resolve_provider(explicit: str | None = None) -> str:
    """Return 'glm' | 'gemini' | 'off'."""
    pref = (explicit or os.environ.get("PROTOCOL_AUDIT_LLM") or "").strip().lower()
    if pref in ("off", "0", "false", "none"):
        return "off"
    if pref in ("glm", "zhipu", "bigmodel"):
        return "glm" if _glm_key() else "off"
    if pref in ("gemini", "google"):
        return "gemini" if _gemini_key() else "off"
    # default: glm if key exists, else gemini, else off
    if _glm_key():
        return "glm"
    if _gemini_key():
        return "gemini"
    return "off"


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _redact(obj: Any) -> Any:
    """Ensure secrets never appear in logged payloads."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            # Do not redact usage counters like prompt_tokens / completion_tokens
            if lk in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens", "latency_ms"):
                out[k] = v
            elif any(s in lk for s in ("api_key", "apikey", "authorization", "bearer", "secret")) or lk.endswith("_token") or lk == "token":
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 40:
        # redact long key-like strings that look like API keys
        for key in filter(None, [_glm_key(), _gemini_key()]):
            if key in obj:
                obj = obj.replace(key, "***REDACTED***")
        return obj
    return obj


def append_llm_log(record: dict[str, Any], log_dir: Path | None = None) -> Path:
    log_dir = log_dir or Path(os.environ.get("PROTOCOL_AUDIT_LLM_LOG_DIR") or DEFAULT_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(SHANGHAI).strftime("%Y%m%d")
    path = log_dir / f"calls-{day}.jsonl"
    safe = _redact(record)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")
    return path


def chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    purpose: str = "generic",
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Call real LLM. Returns {content, provider, model, usage, latency_ms, request_id, ok, error}."""
    prov = resolve_provider(provider)
    started = time.time()
    record: dict[str, Any] = {
        "ts": _now_iso(),
        "purpose": purpose,
        "provider": prov,
        "model": model,
        "ok": False,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "latency_ms": None,
        "request_id": None,
        "error": None,
        "content_preview": None,
        "max_tokens": max_tokens,
        "finish_reason": None,
        "retry_expanded": False,
    }
    if prov == "off":
        record["error"] = "LLM provider off or no API key"
        append_llm_log(record, log_dir)
        return {
            "ok": False,
            "content": "",
            "provider": "off",
            "model": None,
            "usage": {},
            "latency_ms": 0,
            "request_id": None,
            "error": record["error"],
        }

    last_err: Exception | None = None
    result = None
    try:
        for _attempt in range(3):
            try:
                if prov == "glm":
                    result = _call_glm(messages, model=model or "glm-4.6", max_tokens=max_tokens, temperature=temperature)
                else:
                    result = _call_gemini(messages, model=model or "gemini-flash-latest", max_tokens=max_tokens, temperature=temperature)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = f"{type(e).__name__}: {e}"
                if _attempt < 2 and any(x in msg for x in ("RemoteDisconnected", "timeout", "Temporary", "502", "503", "Connection")):
                    time.sleep(2 + _attempt * 3)
                    continue
                raise
        if result is None:
            raise last_err or RuntimeError("LLM call failed")
        latency = int((time.time() - started) * 1000)
        usage = result.get("usage") or {}
        content = result.get("content") or ""
        fr = None
        raw = result.get("raw") or {}
        if isinstance(raw, dict):
            fr = raw.get("finish_reason") or raw.get("finishReason")
        record.update({
            "ok": True,
            "model": result.get("model"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "latency_ms": latency,
            "request_id": result.get("request_id"),
            "content_preview": content[:400],
            "finish_reason": fr,
            "max_tokens": max_tokens,
        })
        append_llm_log(record, log_dir)
        return {
            "ok": True,
            "content": content,
            "provider": prov,
            "model": result.get("model"),
            "usage": usage,
            "latency_ms": latency,
            "request_id": result.get("request_id"),
            "error": None,
            "raw": result.get("raw"),
            "finish_reason": fr,
            "max_tokens": max_tokens,
        }
    except Exception as e:  # noqa: BLE001 — log and surface
        latency = int((time.time() - started) * 1000)
        record.update({"ok": False, "latency_ms": latency, "error": f"{type(e).__name__}: {e}"})
        append_llm_log(record, log_dir)
        return {
            "ok": False,
            "content": "",
            "provider": prov,
            "model": model,
            "usage": {},
            "latency_ms": latency,
            "request_id": None,
            "error": record["error"],
        }


def _call_glm(messages: list[dict[str, str]], *, model: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    key = _glm_key()
    if not key:
        raise RuntimeError("BIGMODEL_CODING_API_KEY missing")
    url = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max(max_tokens, 8192),
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content") or ""
    usage_raw = data.get("usage") or {}
    details = usage_raw.get("completion_tokens_details") or {}
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens"),
        "completion_tokens": usage_raw.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "total_tokens": usage_raw.get("total_tokens"),
    }
    return {
        "content": content,
        "model": data.get("model") or model,
        "usage": usage,
        "request_id": data.get("id"),
        "raw": {"finish_reason": (data.get("choices") or [{}])[0].get("finish_reason")},
    }


def _call_gemini(messages: list[dict[str, str]], *, model: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    key = _gemini_key()
    if not key:
        raise RuntimeError("Gemini API key missing")
    # flatten to single user text with roles labeled
    parts = []
    system = ""
    for m in messages:
        role = m.get("role") or "user"
        if role == "system":
            system += (m.get("content") or "") + "\n"
        else:
            parts.append(f"[{role}]\n{m.get('content') or ''}")
    text = (("System instructions:\n" + system + "\n") if system else "") + "\n\n".join(parts)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max(max_tokens, 2048)},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cands = data.get("candidates") or []
    content = ""
    if cands:
        parts_out = ((cands[0].get("content") or {}).get("parts") or [])
        content = "".join(p.get("text") or "" for p in parts_out)
    um = data.get("usageMetadata") or {}
    usage = {
        "prompt_tokens": um.get("promptTokenCount"),
        "completion_tokens": um.get("candidatesTokenCount"),
        "reasoning_tokens": um.get("thoughtsTokenCount"),
        "total_tokens": um.get("totalTokenCount"),
    }
    return {
        "content": content,
        "model": model,
        "usage": usage,
        "request_id": data.get("responseId"),
        "raw": {},
    }


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse first JSON object from model output (tolerates fences / preamble)."""
    if not text:
        raise ValueError("empty model content")
    s = text.strip()
    # Prefer an explicit ```json ... ``` fence anywhere in the payload.
    marker = "```json"
    low = s.lower()
    idx = low.find(marker)
    if idx >= 0:
        s = s[idx + len(marker) :].lstrip()
        if s.endswith("```"):
            s = s[: -3].rstrip()
    else:
        # Drop leading non-json fences such as ```3WQ1K7D0```
        while s.startswith("```"):
            close = s.find("```", 3)
            if close < 0:
                s = s.lstrip("`")
                break
            s = s[close + 3 :].lstrip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    # find outermost { ... }
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model content")
    return json.loads(s[start : end + 1])


def finish_reason_of(result: dict[str, Any]) -> str | None:
    """Best-effort finish_reason from provider raw payload."""
    raw = result.get("raw") or {}
    if isinstance(raw, dict):
        fr = raw.get("finish_reason") or raw.get("finishReason")
        if fr:
            return str(fr)
    fr2 = result.get("finish_reason")
    return str(fr2) if fr2 else None


def is_length_truncated(result: dict[str, Any], *, requested_max_tokens: int | None = None) -> bool:
    """True when the model stopped because of max output tokens / length."""
    fr = (finish_reason_of(result) or "").lower()
    if fr in ("length", "max_tokens", "max_output_tokens"):
        return True
    usage = result.get("usage") or {}
    completion = usage.get("completion_tokens")
    if requested_max_tokens is not None and completion is not None:
        try:
            if int(completion) >= int(requested_max_tokens):
                return True
        except (TypeError, ValueError):
            pass
    return False


def looks_like_truncated_json(text: str) -> bool:
    """Heuristic: content looks like a cut-off JSON object (unbalanced braces / no close)."""
    if not text or not str(text).strip():
        return True
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    start = s.find("{")
    if start < 0:
        return True
    chunk = s[start:]
    depth = 0
    in_str = False
    esc = False
    for ch in chunk:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if depth != 0:
        return True
    if not chunk.rstrip().endswith("}"):
        return True
    return False
