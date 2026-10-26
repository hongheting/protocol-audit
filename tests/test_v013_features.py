"""V0.1.3: blocker coverage, representative-unit dosing, single-batch CE,
extrapolation severity, soft-dedupe retention."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.claim_evidence import build_claim_evidence_map
from protocol_audit.llm_review import merge_findings
from protocol_audit.optimizer_a import build_group_table, plan_a
from protocol_audit.rules_structural import adjust_extrapolation_severity, run_structural_rules


def test_plan_a_blocker_action_map_covers_all_blockers():
    design = {
        "groups": [{"name": "G1", "treatment": "I+", "control_role_hint": "experimental"}],
        "units": {"allocation_unit": "盆", "subsample_unit": "株"},
    }
    findings = [
        {
            "id": "F03",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "灌水处理与温室台面位置完全混杂",
            "why_invalidates": "水分与台面锁定",
            "fix": "随机化或区组化台面位置",
        },
        {
            "id": "F04",
            "dimension": "controls",
            "severity": "high",
            "category": "confirmed",
            "title": "接种液助剂海藻糖与菌剂效应混杂",
            "why_invalidates": "活菌与助剂不可分",
            "fix": "增加匹配助剂/载体对照",
        },
        {
            "id": "F05",
            "dimension": "endpoints",
            "severity": "blocker",
            "category": "confirmed",
            "title": "破坏性采样破坏终点完整性",
            "why_invalidates": "破坏性取样",
            "fix": "独立牺牲样品",
        },
    ]
    plan = plan_a(design, findings, build_group_table(design))
    covered = {fid for n in plan["change_notes"] for fid in (n.get("addresses_finding_ids") or [])}
    assert "F03" in covered and "F04" in covered and "F05" in covered
    assert plan["optimizer_incomplete"] is False
    assert {m["finding_id"] for m in plan["blocker_action_map"]} == {"F03", "F05"}
    for m in plan["blocker_action_map"]:
        assert m["covered"] is True
        assert m["action"]
        assert m["problem"]
        assert m["verification"]
        assert m["change_note_id"]


def test_plan_a_incomplete_when_blocker_has_no_fix():
    design = {"groups": [{"name": "G1", "treatment": "x"}], "units": {}}
    findings = [
        {
            "id": "F99",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "未知阻断缺陷",
            "why_invalidates": "不可分",
            "fix": "",
        }
    ]
    plan = plan_a(design, findings, build_group_table(design))
    # still gets a placeholder action, but flagged incomplete due to missing fix
    assert any("F99" in (n.get("addresses_finding_ids") or []) for n in plan["change_notes"])
    assert plan["optimizer_incomplete"] is True
    assert "optimizer_incomplete" in plan["completeness_note"] or "占位" in plan["completeness_note"]


def test_representative_unit_dosing_needs_info_not_confirmed_pseudo():
    design = {
        "groups": [],
        "units": {},
        "timepoints": {},
        "controls": [],
        "factors": [],
        "claims_structured": [],
    }
    full = (
        "每日称量代表盆质量，并按该质量变化对同组其余各盆统一补水至目标含水量。"
        "方案未写明逐盆监测与校准。"
    )
    out = run_structural_rules(design, source_file="p.docx", media_type="docx", full_text=full)
    reps = [f for f in out["findings"] if f.get("rule_id") == "structural_representative_unit_dosing"]
    assert len(reps) == 1
    assert reps[0]["category"] == "needs_info"
    assert reps[0]["severity"] in ("medium", "low", "high")
    # must not auto-confirm as pseudoreplication
    assert not (
        reps[0]["category"] == "confirmed" and reps[0]["dimension"] == "pseudoreplication"
    )


def test_single_batch_ce_and_question():
    design = {
        "research_goal_level": "unspecified",
        "hypotheses_structured": [
            {
                "id": "H3",
                "text": "结果可为田间退化旱地推广提供应用依据。",
                "expected_conclusion": "可推广至田间",
                "locations": [],
            }
        ],
        "groups": [{"name": "I+", "treatment": "菌剂", "locations": []}],
        "factors": [],
        "units": {"allocation_unit": "盆"},
        "outcomes": [{"text": "生物量"}],
        "claims_structured": [{"id": "C1", "text": "田间推广", "kind": "extrapolation"}],
    }
    full = "全部接种使用同一批培养菌液。拟为田间退化旱地推广提供应用依据。"
    out = run_structural_rules(design, source_file="b.docx", media_type="docx", full_text=full)
    batch = [f for f in out["findings"] if f.get("rule_id") == "structural_single_batch_material"]
    assert batch and batch[0]["category"] == "needs_info"
    assert any("批次" in (q.get("question") or "") for q in out["clarifying_questions"])
    ce = build_claim_evidence_map(
        design,
        source_file="b.docx",
        media_type="docx",
        full_text=full,
        findings=out["findings"],
    )
    blob = str(ce)
    assert "单批次" in blob or "跨批次" in blob or "批次内" in blob


def test_extrapolation_severity_policy():
    design = {
        "groups": [],
        "units": {},
        "timepoints": {},
        "controls": [],
        "factors": [],
        "claims_structured": [],
    }
    core = (
        "21 d 室内微宇宙。拟据此作为后续工程应用的主要技术依据，满足长期防污要求。"
    )
    out = run_structural_rules(design, source_file="e.docx", media_type="docx", full_text=core)
    ex = [f for f in out["findings"] if f.get("rule_id") == "structural_over_extrapolation"]
    assert ex and ex[0]["severity"] == "blocker"

    mild = (
        "实验室批式结果具有潜在应用前景，但存在局限，不能直接外推至工程，仅供参考。"
    )
    out_m = run_structural_rules(design, source_file="e.docx", media_type="docx", full_text=mild)
    assert not [
        f for f in out_m["findings"] if f.get("rule_id") == "structural_over_extrapolation"
    ]

    llm = [
        {
            "id": "LLM01",
            "dimension": "claim_evidence",
            "severity": "medium",
            "category": "suggestion",
            "title": "盆栽外推至田间退化旱地缺乏依据",
            "why_invalidates": "外推过度",
            "fix": "收紧主张",
            "hard_error": False,
        }
    ]
    adj = adjust_extrapolation_severity(
        llm, "28 d 温室盆栽。为退化旱地田间推广提供应用依据。"
    )
    assert adj[0]["category"] == "confirmed"
    assert adj[0]["severity"] in ("high", "blocker")


def test_soft_dedupe_keeps_both_with_relation():
    rules = [
        {
            "id": "F01",
            "dimension": "endpoints",
            "severity": "high",
            "category": "confirmed",
            "title": "重复取样导致体积/质量变化未校正",
            "why_invalidates": "体积",
            "fix": "校正",
            "locations": [],
            "hard_error": True,
        }
    ]
    llm = [
        {
            "id": "LLM01",
            "dimension": "endpoints",
            "severity": "high",
            "category": "confirmed",
            "title": "动力学取样体积损耗未校正",
            "why_invalidates": "体积未校正",
            "fix": "衡算",
            "locations": [],
            "hard_error": True,
        }
    ]
    merged = merge_findings(rules, llm)
    assert len(merged) == 2
    assert any(f.get("duplicate_relation") == "true_duplicate" for f in merged)
    assert all(f.get("title") for f in merged)
    # different confound mechanisms kept, marked similar_different
    rules2 = [
        {
            "id": "F01",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "因素水平完全锁定混杂，缓冲与pH",
            "why_invalidates": "缓冲",
            "fix": "解耦",
            "locations": [],
            "hard_error": True,
        }
    ]
    llm2 = [
        {
            "id": "LLM01",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "灌水处理与温室台面位置完全混杂",
            "why_invalidates": "台面",
            "fix": "随机化",
            "locations": [],
            "hard_error": True,
        }
    ]
    merged2 = merge_findings(rules2, llm2)
    assert len(merged2) == 2
    # 缓冲×pH vs 台面位置：不同根因，不得仅因「混杂」归组
    assert all(f.get("duplicate_relation", "none") == "none" for f in merged2)
    assert all(not f.get("duplicate_of") for f in merged2)


def test_trial1_tank_plan_a_still_requires_allocation_replicates():
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
    assert plan["optimizer_incomplete"] is False
    assert len(plan["blocker_action_map"]) == 2


def test_single_batch_with_tuiguang_not_upgraded_to_blocker():
    """V0.1.3.1: 「推广」in single-batch title must not trigger extrapolation upgrade."""
    findings = [
        {
            "id": "F04",
            "dimension": "reproducibility",
            "severity": "medium",
            "category": "needs_info",
            "title": "材料/菌剂为单批次制备，跨批次推广边界待明确",
            "why_invalidates": "实验单位重复不等于独立制备批次重复。",
            "fix": "区分批次内效应与跨批次可推广性",
            "hard_error": False,
            "rule_id": "structural_single_batch_material",
        }
    ]
    full = "全部接种使用同一批培养菌液。28 d 温室盆栽。拟为田间退化旱地推广提供应用依据。"
    adj = adjust_extrapolation_severity(findings, full)
    assert adj[0]["category"] == "needs_info"
    assert adj[0]["severity"] != "blocker"
    assert adj[0]["hard_error"] is False


def test_core_extrapolation_still_can_upgrade_to_blocker():
    llm = [
        {
            "id": "LLM01",
            "dimension": "claim_evidence",
            "severity": "medium",
            "category": "suggestion",
            "title": "将短期温室盆栽结果直接外推至退化旱地应用缺乏充分依据",
            "why_invalidates": "外推过度，短周期不能作为田间推广主要依据",
            "fix": "收紧主张",
            "hard_error": False,
        }
    ]
    adj = adjust_extrapolation_severity(
        llm, "28 d 温室盆栽。为退化旱地田间推广提供应用依据。"
    )
    assert adj[0]["category"] == "confirmed"
    assert adj[0]["severity"] in ("high", "blocker")


def test_soft_dedupe_trehalose_vs_bench_independent():
    """Trial3 scenario: 海藻糖对照混杂 vs 台面—水分混杂 must stay independent."""
    rules = [
        {
            "id": "F05",
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "水分处理与温室空间位置（长台层级）完全混杂",
            "why_invalidates": "水分与台面/微气候锁定",
            "fix": "随机化或区组化台面位置",
            "locations": [{"quote": "W上层长台 D下层长台"}],
            "hard_error": True,
        }
    ]
    llm = [
        {
            "id": "LLM08",
            "dimension": "confounding",
            "severity": "high",
            "category": "confirmed",
            "title": "接种液与对照液组成不匹配，海藻糖保护剂引入混杂因素",
            "why_invalidates": "活菌与海藻糖助剂不可分",
            "fix": "匹配助剂/载体对照",
            "locations": [{"quote": "海藻糖保护剂"}],
            "hard_error": True,
        }
    ]
    merged = merge_findings(rules, llm)
    assert len(merged) == 2
    assert all(f.get("duplicate_relation", "none") == "none" for f in merged)
    assert all(not f.get("duplicate_of") for f in merged)
    titles = " ".join(f["title"] for f in merged)
    assert "海藻糖" in titles and "台面" in titles or "长台" in titles or "空间位置" in titles

