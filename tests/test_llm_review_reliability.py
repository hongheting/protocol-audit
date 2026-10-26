"""Unit tests for V0.1.3.3 scientific-review truncation expand-retry (no live LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.llm_review import llm_scientific_review


def _ok_result(content: str, *, max_tokens: int, finish_reason: str, completion_tokens: int | None = None) -> dict[str, Any]:
    ct = completion_tokens if completion_tokens is not None else max_tokens
    return {
        "ok": True,
        "content": content,
        "provider": "glm",
        "model": "glm-4.6",
        "usage": {"prompt_tokens": 50, "completion_tokens": ct, "reasoning_tokens": 0, "total_tokens": 50 + ct},
        "latency_ms": 5,
        "request_id": "rev-test",
        "error": None,
        "raw": {"finish_reason": finish_reason},
        "finish_reason": finish_reason,
        "max_tokens": max_tokens,
    }


GOOD_FINDINGS = {
    "findings": [
        {
            "dimension": "confounding",
            "severity": "high",
            "category": "confirmed",
            "title": "处理与台面分区绑定导致空间混杂",
            "quote": "容器按处理组集中摆放在同一实验台的不同区域",
            "why_invalidates": "处理与位置完全绑定",
            "fix": "随机化或区组化摆放",
        }
    ]
}


def test_review_expand_retry_succeeds_after_first_truncation():
    truncated = '{"findings": [{"title": "x", "quote": "y"'  # cut off
    good = json.dumps(GOOD_FINDINGS, ensure_ascii=False)
    calls: list[int] = []

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        calls.append(tok)
        if tok <= 8192:
            return _ok_result(truncated, max_tokens=tok, finish_reason="length", completion_tokens=tok)
        return _ok_result(good, max_tokens=tok, finish_reason="stop", completion_tokens=200)

    design = {"hypotheses": [], "groups": [], "units": {}}
    with patch("protocol_audit.llm_review.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_review.resolve_provider", return_value="glm"):
            out = llm_scientific_review(
                design,
                source_file="t.md",
                media_type="text/markdown",
                full_text="容器按处理组集中摆放。统计用 ANOVA。",
            )

    assert out["llm_meta"]["ok"] is True
    assert out["llm_meta"]["review_status"] == "complete"
    assert out["llm_meta"]["partial_review"] is False
    assert out["llm_meta"]["truncation_detected"] is True
    assert out["llm_meta"]["expanded_retry"] is True
    assert out["findings"], "expected LLM findings after successful expand"
    assert all(f.get("origin") == "llm_review" for f in out["findings"])
    assert calls == [8192, 16384]


def test_review_double_truncation_marks_partial_not_fake_complete():
    truncated = '{"findings": [{"title": "x"'  # never closes

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        return _ok_result(truncated, max_tokens=tok, finish_reason="length", completion_tokens=tok)

    design = {"hypotheses": [], "groups": []}
    with patch("protocol_audit.llm_review.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_review.resolve_provider", return_value="glm"):
            out = llm_scientific_review(
                design,
                source_file="t.md",
                media_type="text/markdown",
                full_text="示例方案正文。",
            )

    assert out["llm_meta"]["ok"] is False
    assert out["llm_meta"]["partial_review"] is True or out["llm_meta"]["review_status"] == "failed"
    assert out["llm_meta"]["pretend_complete_llm_review"] is False
    assert out["llm_meta"]["expanded_retry"] is True
    # Must not pretend a successful complete LLM review with empty findings
    assert out["review_status"] in ("failed", "partial")
    assert out["findings"] == []


def test_review_keeps_first_when_expand_worse():
    """Expand retry must not discard a usable first JSON when the expand call is garbage."""
    good = json.dumps(GOOD_FINDINGS, ensure_ascii=False)
    calls: list[int] = []

    def fake_chat(**kwargs):
        tok = kwargs["max_tokens"]
        calls.append(tok)
        if tok <= 8192:
            # Heuristic truncation look: unfinished fence triggers expand, but JSON body is valid.
            # Use finish_reason=length so need_retry is True, yet content parses.
            return _ok_result(good, max_tokens=tok, finish_reason="length", completion_tokens=tok)
        # Expand returns unusable content
        return _ok_result("```3WQ1K7D0``` (Internal marker, ignore) not-json", max_tokens=tok, finish_reason="stop", completion_tokens=20)

    design = {"hypotheses": [], "groups": []}
    with patch("protocol_audit.llm_review.chat_completion", side_effect=fake_chat):
        with patch("protocol_audit.llm_review.resolve_provider", return_value="glm"):
            out = llm_scientific_review(
                design,
                source_file="t.md",
                media_type="text/markdown",
                full_text="容器按处理组集中摆放。统计用 ANOVA。",
            )

    assert calls == [8192, 16384]
    assert out["findings"], "must keep first-pass findings when expand is worse"
    assert out["llm_meta"]["expanded_retry"] is True
    assert out["llm_meta"]["pretend_complete_llm_review"] is False
    # first was length-truncated → may be complete or partial depending on accept path; must not be empty-failed facade
    assert out["review_status"] in ("complete", "partial")
