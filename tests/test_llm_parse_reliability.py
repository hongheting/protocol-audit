"""Unit tests for V0.1.2.1 design-extract truncation expand-retry (no live LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from typing import Any
from unittest.mock import patch

import pytest

from protocol_audit.llm_client import is_length_truncated, looks_like_truncated_json
from protocol_audit.llm_parse import LLMParseError, llm_extract_design
from protocol_audit.pipeline import build_parse_preview


GOOD_EXTRACT = {
    "parse_status": "ok",
    "research_question": "test",
    "research_goal_level": "unspecified",
    "hypotheses": [],
    "factors": [],
    "groups": [],
    "controls": [],
    "units": {"status": "unknown"},
    "timepoints": {"status": "unknown"},
    "endpoints": [],
    "claims": [],
    "tables": [],
    "unknowns": [],
}


def _ok_result(content: str, *, max_tokens: int, finish_reason: str, completion_tokens: int | None = None) -> dict[str, Any]:
    ct = completion_tokens if completion_tokens is not None else max_tokens
    return {
        "ok": True,
        "content": content,
        "provider": "glm",
        "model": "glm-4.6",
        "usage": {"prompt_tokens": 100, "completion_tokens": ct, "reasoning_tokens": 0, "total_tokens": 100 + ct},
        "latency_ms": 10,
        "request_id": "test-req",
        "error": None,
        "raw": {"finish_reason": finish_reason},
        "finish_reason": finish_reason,
        "max_tokens": max_tokens,
    }


def test_is_length_truncated_by_finish_reason_and_tokens():
    assert is_length_truncated(
        {"finish_reason": "length", "usage": {"completion_tokens": 100}, "raw": {"finish_reason": "length"}},
        requested_max_tokens=8192,
    )
    assert is_length_truncated(
        {"finish_reason": "stop", "usage": {"completion_tokens": 8192}, "raw": {"finish_reason": "stop"}},
        requested_max_tokens=8192,
    )
    assert not is_length_truncated(
        {"finish_reason": "stop", "usage": {"completion_tokens": 100}, "raw": {"finish_reason": "stop"}},
        requested_max_tokens=8192,
    )


def test_looks_like_truncated_json_unbalanced():
    assert looks_like_truncated_json('{"a": 1, "b":')
    assert looks_like_truncated_json("")
    assert not looks_like_truncated_json(json.dumps({"a": 1, "b": [1, 2]}))


def test_expand_retry_succeeds_after_first_truncation():
    truncated = '{"parse_status": "ok", "research_question": "x", "hypotheses": ['  # cut off
    good = json.dumps(GOOD_EXTRACT, ensure_ascii=False)

    calls: list[int] = []

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        calls.append(tok)
        if tok <= 8192:
            return _ok_result(truncated, max_tokens=tok, finish_reason="length", completion_tokens=tok)
        return _ok_result(good, max_tokens=tok, finish_reason="stop", completion_tokens=200)

    with patch("protocol_audit.llm_parse.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_parse.resolve_provider", return_value="glm"):
            out = llm_extract_design(
                [{"paragraph_id": "p-1", "text": "示例方案", "block_type": "paragraph"}],
                source_file="t.md",
                media_type="text/markdown",
                provider="glm",
            )

    assert out["design_extract"] is not None
    assert out["llm_meta"]["ok"] is True
    assert out["llm_meta"]["hard_fail"] is False
    assert out["llm_meta"]["fallback"] is False
    assert out["llm_meta"]["truncation_detected"] is True
    assert out["llm_meta"]["expanded_retry"] is True
    assert out["llm_meta"]["max_tokens_used"] == 16384
    assert calls == [8192, 16384]


def test_double_truncation_hard_fails_no_fake_success():
    truncated = '{"parse_status": "ok", "groups": [{"name": "A"'  # never closes

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        return _ok_result(truncated, max_tokens=tok, finish_reason="length", completion_tokens=tok)

    with patch("protocol_audit.llm_parse.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_parse.resolve_provider", return_value="glm"):
            out = llm_extract_design(
                [{"paragraph_id": "p-1", "text": "示例", "block_type": "paragraph"}],
                source_file="t.md",
                media_type="text/markdown",
                provider="glm",
                allow_heuristic_fallback=False,
            )

    assert out["design_extract"] is None
    assert out["llm_meta"]["ok"] is False
    assert out["llm_meta"]["hard_fail"] is True
    assert out["llm_meta"]["fallback"] is False
    assert out["llm_meta"]["expanded_retry"] is True
    assert "expand retry" in (out["llm_meta"].get("error") or "").lower() or "截断" in (out["llm_meta"].get("error") or "") or "truncated" in (out["llm_meta"].get("error") or "").lower() or "JSON parse failed" in (out["llm_meta"].get("error") or "")


def test_pipeline_raises_on_hard_fail(tmp_path):
    md = tmp_path / "p.md"
    md.write_text("# 方案\n\n处理组 A 与对照 B。\n", encoding="utf-8")
    truncated = '{"parse_status": "ok", "hypotheses": ['

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        return _ok_result(truncated, max_tokens=tok, finish_reason="length", completion_tokens=tok)

    with patch("protocol_audit.llm_parse.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_parse.resolve_provider", return_value="glm"):
            with patch("protocol_audit.pipeline.resolve_provider", return_value="glm"):
                with pytest.raises(LLMParseError) as ei:
                    build_parse_preview(path=md, use_llm_parse=True, llm_provider="glm")
    assert ei.value.llm_meta.get("hard_fail") is True
