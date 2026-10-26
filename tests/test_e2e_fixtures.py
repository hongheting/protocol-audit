"""E2E fixture tests for ProtocolAudit skeleton A."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.pipeline import audit_file, build_parse_preview, run_audit
from protocol_audit.preview import public_preview
from protocol_audit.schema_validate import validate

FIXTURES = ROOT / "fixtures"


def test_flawed_docx_triggers_real_findings():
    pub, report = audit_file(FIXTURES / "flawed_protocol.docx", research_goal_level="unspecified")
    errs = validate("report", report)
    assert not errs, errs

    cats = {f["category"] for f in report["findings"]}
    assert "confirmed" in cats or "needs_info" in cats

    dims = {f["dimension"] for f in report["findings"]}
    assert "claim_evidence" in dims  # mechanism without intervention
    assert "pseudoreplication" in dims or any(
        q["blocks_dimensions"] and "pseudoreplication" in q["blocks_dimensions"]
        for q in report["clarifying_questions"]
    )
    assert "controls" in dims  # missing solvent

    # must have locations
    for f in report["findings"]:
        assert f.get("locations") and len(f["locations"]) >= 1
        assert f["locations"][0].get("original_text")

    assert report["claim_evidence_map"]["rows"]
    assert any("介导" in r["claim"] or "ROS" in r["claim"] for r in report["claim_evidence_map"]["rows"])
    assert report["optimizer"]["plan_id"] == "A"
    assert report["optimizer"]["change_notes"]
    assert report["research_goal_level"] == "unspecified"
    assert report["research_goal_level_source"] in ("default", "user", "inferred")
    # never silently become mechanism without user
    assert not (
        report["research_goal_level"] == "mechanism_causal"
        and report["research_goal_level_source"] == "inferred"
    )


def test_sound_md_is_milder():
    pub, report = audit_file(FIXTURES / "sound_protocol.md", research_goal_level="unspecified")
    errs = validate("report", report)
    assert not errs, errs

    # Should not flag mechanism gap as blocker
    mech_blockers = [
        f for f in report["findings"]
        if f["dimension"] == "claim_evidence" and f["severity"] == "blocker"
    ]
    assert not mech_blockers

    # Should recognize biological replicates / solvent
    confirmed_control_gaps = [
        f for f in report["findings"]
        if f["dimension"] == "controls" and f["category"] == "confirmed" and "溶剂" in f["title"]
    ]
    # sound has solvent — should not confirm missing solvent
    assert not confirmed_control_gaps

    # ambiguous parallel should be absent or mild
    pseudo_needs = [
        f for f in report["findings"]
        if f["dimension"] == "pseudoreplication" and f["category"] == "needs_info"
        and "未写清" in f["title"]
    ]
    assert not pseudo_needs

    assert report["optimizer"]["plan_id"] == "A"
    assert report["summary"]["verdict"] in (
        "ready_with_fixes",
        "awaiting_clarification",
        "insufficient_info",
        "needs_redesign",
    )


def test_preview_schema_and_confirm_gate():
    preview = build_parse_preview(path=FIXTURES / "flawed_protocol.md")
    pub = public_preview(preview)
    errs = validate("preview", pub)
    assert not errs, errs
    assert pub["user_confirmed"] is False

    with pytest.raises(ValueError):
        run_audit(preview, confirm_design=False)

    report = run_audit(preview, confirm_design=True)
    assert report["design_confirmation"]["status"] == "confirmed"
    assert validate("report", report) == []


def test_scanned_pdf_warns_and_manual_table_continues():
    preview = build_parse_preview(path=FIXTURES / "scanned_empty.pdf")
    pub = public_preview(preview)
    assert pub["parse_warnings"]
    assert pub.get("limited_audit_recommended") is True
    assert any(u.get("asset_type") == "scanned_table" for u in pub.get("unparsed_assets") or [])

    table = "| 组别 | 处理 | n |\n| --- | --- | --- |\n| 空白 | 无 | 3 |\n| 处理 | X | 3 |"
    preview2 = build_parse_preview(
        path=FIXTURES / "scanned_empty.pdf",
        manual_supplements=[{
            "id": "manual-1",
            "kind": "table",
            "text": table,
            "source": "manual_input",
            "replaces_unparsed_asset_id": "U-scanned-table-1",
        }],
    )
    assert any(b.get("source") == "manual_input" for b in preview2["ingested_blocks"])
    report = run_audit(preview2, confirm_design=True)
    assert report["schema_version"] == "0.2.1"
    # still may be limited if groups thin, but pipeline completes
    assert "findings" in report
    assert report["optimizer"]["plan_id"] == "A"


def test_flawed_md_and_docx_both_run():
    _, r1 = audit_file(FIXTURES / "flawed_protocol.md")
    _, r2 = audit_file(FIXTURES / "flawed_protocol.docx")
    assert r1["summary"]["confirmed_count"] + r1["summary"]["needs_info_count"] >= 1
    assert r2["summary"]["confirmed_count"] + r2["summary"]["needs_info_count"] >= 1
