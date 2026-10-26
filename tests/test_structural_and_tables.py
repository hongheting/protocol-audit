"""New tests: table classification, container confound, pseudoreplication."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.llm_parse import merge_llm_into_design
from protocol_audit.pipeline import audit_file, build_parse_preview, run_audit
from protocol_audit.rules_structural import run_structural_rules
from protocol_audit.schema_validate import validate


def test_table_kind_not_treated_as_groups():
    heuristic = {
        "groups": [
            {"name": "方案版本", "treatment": "v0.4", "status": "inferred", "locations": []},
            {"name": "D7", "treatment": "采样", "status": "inferred", "locations": []},
            {"name": "B1", "treatment": "基础涂层", "status": "stated", "locations": []},
        ],
        "research_goal_level": "unspecified",
        "research_goal_level_source": "default",
        "hypotheses": [],
        "controls": [],
        "outcomes": [],
        "replication": {},
        "claims": [],
        "field_meta": {},
    }
    extract = {
        "parse_status": "ok",
        "hypotheses": [{"id": "H1", "text": "颗粒降低附着", "status": "stated", "locations": []}],
        "groups": [
            {"name": "B0", "treatment": "裸不锈钢", "container_id": "A", "role": "reference", "n_claimed": "3", "status": "stated", "locations": []},
            {"name": "B1", "treatment": "基础涂层", "container_id": "A", "role": "control", "n_claimed": "3", "status": "stated", "locations": []},
            {"name": "D7", "treatment": "时间点", "status": "stated", "locations": []},
        ],
        "tables": [
            {"table_id": "t-1", "table_kind": "metadata_table", "caption": "版本"},
            {"table_id": "t-2", "table_kind": "treatment_group_table", "caption": "分组"},
            {"table_id": "t-3", "table_kind": "sampling_schedule_table", "caption": "采样"},
        ],
        "controls": [],
        "units": {"allocation_unit": "水槽", "subsample_unit": "挂板", "status": "stated"},
        "timepoints": {"points": ["D0", "D7"], "status": "stated"},
        "endpoints": [],
        "claims": [],
        "unknowns": [],
    }
    merged = merge_llm_into_design(heuristic, extract)
    names = [g["name"] for g in merged["groups"]]
    assert "B0" in names and "B1" in names
    assert "D7" not in names
    assert "方案版本" not in names
    kinds = {t["table_kind"] for t in merged["table_classifications"]}
    assert "metadata_table" in kinds and "sampling_schedule_table" in kinds


def test_structural_container_confound_and_pseudo():
    design = {
        "groups": [
            {"name": "B1", "treatment": "基础 无UV", "container_id": "A", "factor_levels": {"UV": "否"}, "locations": []},
            {"name": "B2", "treatment": "功能 无UV", "container_id": "A", "factor_levels": {"UV": "否"}, "locations": []},
            {"name": "B3", "treatment": "基础 有UV", "container_id": "B", "factor_levels": {"UV": "是"}, "locations": []},
            {"name": "B4", "treatment": "功能 有UV", "container_id": "B", "factor_levels": {"UV": "是"}, "locations": []},
        ],
        "units": {
            "allocation_unit": "水槽",
            "subsample_unit": "挂板",
            "independent_experimental_unit": "挂板",
            "nesting": "挂板 nested in 水槽",
            "locations": [],
        },
        "timepoints": {
            "points": ["D7", "D14", "D21"],
            "destructive_assay": True,
            "returned_after_assay": True,
            "status": "stated",
        },
        "controls": [],
        "factors": [{"name": "颗粒", "levels": ["0", "1.5%"]}, {"name": "UV", "levels": ["否", "是"]}],
        "claims_structured": [],
        "statistical_plan": "one-way ANOVA + Tukey；B4低于B2与B3且降幅最大即判定协同",
    }
    full = (
        "UV-C 模块安装在 B 水槽上方；A 水槽不安装光源。"
        "暂不另外设置水槽层面的平行。"
        "将每组 3 片挂板视为 3 个平行样。挂板作为独立样本，取 n = 3。"
        "功能颗粒先以少量有机助溶剂预分散；不另设置助溶剂单独处理组。"
        "测定结束后以去离子水轻轻冲洗挂板表面，再放回原水槽继续培养。"
        "D7、D14、D21 按独立时间点分别分析。"
        "若 B4 的平均附着量显著低于 B2 与 B3，同时 B4 的降低幅度最大，即判定协同。"
        "若接触角与附着生物量呈显著相关，则认定为主要防污机制。"
        "拟据此提出能够满足淡水取水口长期防污要求，并作为后续工程应用的主要技术依据。"
        "同一组的 3 片挂板样品混合后测定。"
        "各组挂板按编号顺序依次排列，运行期间不调整位置。"
        "暂不进行挂板表面的水下实际辐照剂量测定。"
    )
    out = run_structural_rules(design, source_file="t.docx", media_type="docx", full_text=full)
    titles = " ".join(f["title"] for f in out["findings"])
    assert "混杂" in titles
    assert "伪重复" in titles
    assert "助溶剂" in titles
    assert "协同" in titles or "交互" in titles
    assert "破坏性" in titles
    assert "机制" in titles or "相关" in titles
    assert "外推" in titles or "工程" in titles
    # must be confirmed for core
    core = [f for f in out["findings"] if f["category"] == "confirmed" and f["severity"] in ("blocker", "high")]
    assert len(core) >= 4


def test_no_false_missing_blank_when_b0_present():
    from protocol_audit.rules import run_rules
    design = {
        "research_goal_level": "unspecified",
        "research_goal_level_source": "default",
        "hypotheses": ["H1：颗粒降低附着"],
        "hypotheses_structured": [{"id": "H1", "text": "颗粒降低附着", "status": "stated", "locations": []}],
        "groups": [
            {"name": "B0", "treatment": "裸不锈钢", "control_role_hint": "reference", "locations": []},
            {"name": "B1", "treatment": "基础涂层", "control_role_hint": "control", "locations": []},
        ],
        "controls": [{"type": "reference", "label": "B0", "present": True, "status": "stated", "locations": []}],
        "outcomes": [{"text": "附着量", "status": "stated", "locations": []}],
        "replication": {"text": "3", "status": "stated", "ambiguous_parallel": False, "has_biological": True, "has_technical": True, "locations": []},
        "claims": [],
        "field_meta": {},
        "_hits": {},
        "statistical_plan": "t-test",
        "statistics_status": "stated",
    }
    out = run_rules(design, source_file="x.md", media_type="text/markdown", full_text="B0 作为裸基材参照组。B1 基础涂层。")
    bad = [f for f in out["findings"] if "缺少空白" in f["title"]]
    assert not bad


@pytest.mark.llm
def test_llm_trial1_optional():
    """Real LLM call — skipped unless RUN_LLM_TESTS=1."""
    import os
    if os.environ.get("RUN_LLM_TESTS") != "1":
        pytest.skip("set RUN_LLM_TESTS=1 for live LLM")
    _, report = audit_file(
        ROOT / "real-trials" / "trial1.docx",
        use_llm_parse=True,
        use_llm_review=True,
        llm_provider="glm",
    )
    assert validate("report", report) == []
    titles = " ".join(f["title"] for f in report["findings"])
    assert "混杂" in titles or "伪重复" in titles
    assert not any("缺少空白" in f["title"] for f in report["findings"])


def test_generic_factor_lock_volume_cocktail_regen_process():
    """Domain-agnostic structural rules (adsorption-like text, no UV/tank)."""
    design = {
        "groups": [
            {"name": "G0", "treatment": "无材料空白", "locations": []},
            {"name": "G1", "treatment": "原始材料", "locations": []},
            {"name": "G2", "treatment": "改性材料", "locations": []},
        ],
        "units": {
            "allocation_unit": "锥形瓶",
            "subsample_unit": "悬液取样",
            "independent_experimental_unit": "独立反应瓶",
            "locations": [],
        },
        "timepoints": {"points": ["5min", "360min"], "status": "stated"},
        "controls": [{"type": "blank", "label": "G0", "present": True}],
        "factors": [
            {"name": "初始pH", "levels": ["5.0", "7.0", "9.0"]},
            {"name": "共存组分", "levels": ["无", "混合"]},
        ],
        "claims_structured": [
            {"id": "C1", "text": "表征证明主导机制", "kind": "mechanism"},
        ],
        "statistical_plan": "单因素方差分析",
    }
    full = (
        "称取材料加入溶液浸渍 12 h，过滤后热处理 2 h 得到改性材料。"
        "原始材料按筛分后的方式直接用于吸附实验。"
        "分别使用柠檬酸盐、HEPES 和硼酸盐缓冲体系，将反应体系初始 pH 调节至 5.0、7.0 和 9.0，"
        "实验不另外设置相同 pH 下的缓冲体系对照。"
        "在另一组水样中同时加入 Ca²⁺、Mg²⁺、HCO₃⁻和腐殖酸以模拟综合影响，"
        "通过比较终点去除率，重点讨论碳酸氢根与目标离子的竞争作用。"
        "动力学实验同管依次取样，取样后不补加新液；按固定的初始体积 50 mL 计算各时刻表观吸附量。"
        "重复吸附—碱洗—再吸附共 5 轮；材料只在首轮投加前和第 5 轮结束后称量干质量，"
        "中间各轮不重新调整投加量。"
        "XPS 结合能变化将用于说明特异性结合是提升性能的主导机制。"
        "若连续 5 轮再生后仍保持高去除率，则可为连续运行单元提供材料依据。"
    )
    out = run_structural_rules(design, source_file="ads.docx", media_type="docx", full_text=full)
    ids = {f.get("rule_id") for f in out["findings"]}
    titles = " ".join(f["title"] for f in out["findings"])
    assert "structural_factor_lock" in ids
    assert "structural_uncorrected_depletion" in ids
    assert "structural_cocktail_attribution" in ids
    assert "structural_regen_mass_balance" in ids
    assert "structural_process_blank" in ids
    assert "structural_corr_not_cause" in ids
    # must NOT invent trial1 UV/tank findings on this text
    assert "UV" not in titles
    assert "挂板" not in titles
    assert "水槽" not in titles


def test_claim_evidence_and_plan_a_no_trial1_bleed_on_adsorption():
    from protocol_audit.claim_evidence import build_claim_evidence_map
    from protocol_audit.optimizer_a import build_group_table, plan_a

    design = {
        "research_goal_level": "unspecified",
        "hypotheses_structured": [
            {
                "id": "H1",
                "text": "改性显著提高去除能力，且提高主要来源于特异性结合。",
                "expected_conclusion": "改性组高于基线，特异性结合是主导机制",
                "locations": [],
            },
            {
                "id": "H2",
                "text": "在不同 pH 和共存组分条件下仍保持较高去除能力。",
                "expected_conclusion": "具有选择性与适应性",
                "locations": [],
            },
            {
                "id": "H3",
                "text": "经多轮再生后仍稳定，可为连续运行单元提供材料依据。",
                "expected_conclusion": "再生稳定并可支撑连续运行",
                "locations": [],
            },
        ],
        "groups": [
            {"name": "G0", "treatment": "无材料空白", "control_role_hint": "blank", "n_claimed": "3"},
            {"name": "G1", "treatment": "原始材料", "control_role_hint": "reference", "n_claimed": "3"},
            {"name": "G2", "treatment": "改性材料", "control_role_hint": "experimental", "n_claimed": "3"},
        ],
        "factors": [
            {"name": "初始pH", "levels": ["5", "7", "9"]},
            {"name": "共存组分", "levels": ["无", "混合"]},
        ],
        "units": {
            "allocation_unit": "锥形瓶",
            "subsample_unit": "悬液取样",
            "independent_experimental_unit": "独立反应瓶",
        },
        "outcomes": [
            {"text": "去除率", "supports_claims": ["H1", "H2", "H3"]},
            {"text": "表面表征", "supports_claims": ["H1"]},
        ],
        "claims_structured": [{"id": "C3", "text": "可为连续运行提供依据", "kind": "extrapolation"}],
    }
    findings = [
        {
            "id": "F02",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "因素水平完全锁定混杂，目标因子主效应不可单独估计",
            "why_invalidates": "缓冲与pH锁定",
            "fix": "解耦缓冲与pH",
            "rule_id": "structural_factor_lock",
        },
        {
            "id": "F03",
            "dimension": "endpoints",
            "severity": "high",
            "category": "confirmed",
            "title": "重复取样导致体积/质量变化未校正",
            "why_invalidates": "不补液",
            "fix": "校正体积",
            "rule_id": "structural_uncorrected_depletion",
        },
        {
            "id": "F04",
            "dimension": "confounding",
            "severity": "high",
            "category": "confirmed",
            "title": "混合暴露（多组分同时加入）却声称单一组分归因",
            "why_invalidates": "鸡尾酒",
            "fix": "单因子设计",
            "rule_id": "structural_cocktail_attribution",
        },
    ]
    full = "改性材料吸附实验。pH与缓冲。同时加入多组分。可为连续运行单元提供材料依据。"
    ce = build_claim_evidence_map(
        design, source_file="a.docx", media_type="docx", full_text=full, findings=findings
    )
    blob = json_dumps_ce(ce)
    for banned in ("UV", "水槽", "挂板", "润湿", "功能颗粒", "涂层"):
        assert banned not in blob, banned
    assert any(r.get("hypothesis_id") == "H2" for r in ce["rows"])

    gt = build_group_table(design)
    plan = plan_a(design, findings, gt)
    plan_blob = str(plan)
    for banned in ("UV", "水槽", "挂板", "润湿", "功能颗粒"):
        assert banned not in plan_blob, f"Plan A leaked {banned}"
    notes = " ".join(n["summary"] for n in plan["change_notes"])
    assert "解耦" in notes or "锁定" in notes or "校正" in notes or "单因子" in notes


def json_dumps_ce(ce):
    import json
    return json.dumps(ce, ensure_ascii=False)


def test_plan_a_trial1_still_mentions_allocation_unit_when_tank_findings():
    from protocol_audit.optimizer_a import build_group_table, plan_a

    design = {
        "groups": [
            {"name": "B1", "treatment": "基础 无UV", "control_role_hint": "negative", "n_claimed": "3"},
            {"name": "B4", "treatment": "功能 有UV", "control_role_hint": "experimental", "n_claimed": "3"},
        ],
        "units": {
            "allocation_unit": "水槽",
            "subsample_unit": "挂板",
            "independent_experimental_unit": "挂板",
            "nesting": "挂板 nested in 水槽",
        },
    }
    findings = [
        {
            "id": "F01",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "处理因素与实验容器完全混杂",
            "why_invalidates": "UV与水槽一一对应",
            "fix": "容器层面重复",
            "rule_id": "structural_container_confound",
        },
        {
            "id": "F02",
            "dimension": "pseudoreplication",
            "severity": "blocker",
            "category": "confirmed",
            "title": "伪重复：子样本被当作独立实验单位",
            "why_invalidates": "挂板当n",
            "fix": "以水槽为独立单位",
            "rule_id": "structural_pseudoreplication",
        },
    ]
    plan = plan_a(design, findings, build_group_table(design))
    notes = " ".join(n["summary"] for n in plan["change_notes"])
    assert "水槽" in notes
    assert "统计模型" in notes or "ANOVA" in notes
