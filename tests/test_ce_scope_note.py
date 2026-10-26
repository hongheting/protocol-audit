"""V0.1.3.3: research limitation sentences must not become EXTRAP claims."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.claim_evidence import (
    _is_scope_limitation,
    build_claim_evidence_map,
)


def test_is_scope_limitation_positive():
    assert _is_scope_limitation(
        "结论主要适用于本次水源、涂层配方和试验条件；关于长期现场性能及普遍作用机制的判断，需要结合后续独立验证。"
    )
    assert _is_scope_limitation("本研究结论仅适用于实验室短期条件，不能直接外推至工程连续运行。")


def test_is_scope_limitation_rejects_affirmative_overclaim():
    assert not _is_scope_limitation("28 天实验室结果可作为长期工程应用的主要技术依据。")


def test_scope_note_not_extrap_supports_no():
    design = {
        "hypotheses_structured": [
            {"id": "H1", "text": "处理降低附着", "expected_conclusion": "处理组附着更低", "status": "stated", "locations": []},
        ],
        "claims_structured": [
            {
                "id": "C3",
                "text": "结论主要适用于本次水源、涂层配方和试验条件；关于长期现场性能及普遍作用机制的判断，需要结合后续独立验证。",
                "kind": "extrapolation",  # mis-tagged by extract — postprocess must fix
                "status": "stated",
                "locations": [],
            }
        ],
        "groups": [{"name": "CA3", "treatment": "3%"}],
        "outcomes": [{"text": "OD590", "supports_claims": ["H1"]}],
        "research_goal_level": "unspecified",
    }
    full = (
        "微宇宙评价。结论主要适用于本次水源、涂层配方和试验条件；"
        "关于长期现场性能及普遍作用机制的判断，需要结合后续独立验证。"
    )
    ce = build_claim_evidence_map(
        design, source_file="t.md", media_type="text/markdown", full_text=full, findings=[]
    )
    rows = ce["rows"]
    extrap = [r for r in rows if r.get("hypothesis_id") == "EXTRAP"]
    scopes = [r for r in rows if r.get("row_kind") == "scope_note" or r.get("hypothesis_id") == "SCOPE"]
    assert not extrap, f"limitation must not become EXTRAP: {extrap}"
    assert scopes, "expected scope_note row"
    assert scopes[0]["design_supports"] == "yes"
    assert "限制" in scopes[0]["judgment"] or "边界" in scopes[0]["judgment"] or "scope" in scopes[0]["judgment"].lower()


def test_affirmative_extrap_still_creates_extrap_row():
    design = {
        "hypotheses_structured": [],
        "claims_structured": [
            {
                "id": "C1",
                "text": "本研究结果可作为长期工程应用的主要技术依据。",
                "kind": "extrapolation",
                "status": "stated",
                "locations": [],
            }
        ],
        "groups": [],
        "research_goal_level": "unspecified",
    }
    full = "本研究结果可作为长期工程应用的主要技术依据。"
    ce = build_claim_evidence_map(
        design, source_file="t.md", media_type="text/markdown", full_text=full, findings=[]
    )
    extrap = [r for r in ce["rows"] if r.get("hypothesis_id") == "EXTRAP"]
    assert extrap
    assert extrap[0]["design_supports"] == "no"
    assert extrap[0].get("row_kind", "claim") == "claim"
