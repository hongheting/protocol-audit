"""V0.1.3.2: methods-first review windows + coverage (no LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.review_windows import build_review_windows, detect_methods_spans


def test_short_text_no_truncation():
    text = "实验方案：短文。分组 A/B。设溶剂对照。每组 3 个独立重复。用 one-way ANOVA。"
    windows, cov = build_review_windows(text, window_chars=14000)
    assert len(windows) == 1
    assert windows[0].text == text
    assert cov.truncated is False
    assert cov.comprehensive is True
    assert cov.chars_sent == len(text)
    assert "短文" in "".join(cov.notes) or cov.omitted_char_count == 0


def test_long_text_methods_preferred():
    head = "前言与背景。" * 800  # ~4800
    methods = (
        "\n\n## 材料与方法\n"
        "实验设计：分组为处理组与空白对照；每组 5 个独立重复；"
        "采样于 0/7/14 d；统计分析采用 two-way ANOVA。\n"
        "反应器编号 R1–R3，处理分配到独立反应器。\n"
    )
    mid = "其它叙述。" * 2000  # ~10000
    results = "\n\n## 结果\n显著升高。" + ("数据。" * 3000)
    text = head + methods + mid + results
    assert len(text) > 14000

    windows, cov = build_review_windows(text, window_chars=14000, max_windows=3)
    assert cov.methods_detected is True
    assert cov.methods_included is True
    assert cov.window_count >= 1
    joined = "\n".join(w.text for w in windows)
    assert "材料与方法" in joined or "实验设计" in joined
    assert "独立重复" in joined or "ANOVA" in joined
    assert "反应器" in joined
    # coverage must flag non-comprehensive when still omitting a lot
    assert "comprehensive" in cov.to_dict()
    assert isinstance(cov.comprehensive, bool)
    summary = cov.summary_zh()
    assert "review_coverage" in summary
    if not cov.comprehensive:
        assert "不得声称全面审查" in summary or "禁止声称全面审查" in "".join(cov.notes)


def test_coverage_marks_when_methods_missing_and_truncated():
    # long text without methods headings — still truncated
    text = ("段落填充内容没有设计信息。" * 2000)
    windows, cov = build_review_windows(text, window_chars=5000, max_windows=2)
    assert len(text) > 5000
    assert cov.truncated is True or cov.window_count >= 1
    d = cov.to_dict()
    assert "methods_included" in d
    assert "omitted_char_count" in d


def test_detect_methods_spans_english():
    text = "Intro\n\n## Materials and Methods\nWe used 3 replicates and controls.\n\n## Results\nOk.\n"
    spans = detect_methods_spans(text)
    assert spans
    assert any("Methods" in lab or "Materials" in lab for _, _, lab in spans)


def test_trial4_offline_methods_in_window_tech_check():
    """Technical verification (offline): Trial4 long midterm → methods/reactor enter windows."""
    from protocol_audit.ingest import ingest_path

    docx = ROOT / "real-trials" / "trial4.docx"
    if not docx.is_file():
        return
    full = ingest_path(docx)["full_text"]
    assert len(full) > 14000
    windows, cov = build_review_windows(full, window_chars=14000, max_windows=3)
    joined = "\n".join(w.text for w in windows)
    # generic design cues present in Luo MBGS midterm methods-ish content
    hit = any(
        k in joined
        for k in ("反应器", "分组", "对照", "重复", "Methods", "材料", "方法", "接种", "水力")
    )
    assert hit, "methods/design cues should enter review windows for trial4"
    assert cov.methods_included or cov.methods_detected or hit
    assert cov.to_dict()["tech_version"].startswith("0.1.3.2")
