"""Core design rules: legacy keyword checks + structural hard gates.

Confirmed findings must not be produced from keywords alone when structure is ambiguous.
Claim–Evidence mapping is built in claim_evidence.py (per-hypothesis).
"""
from __future__ import annotations

import re
from typing import Any

from .claim_evidence import build_claim_evidence_map
from .locators import fallback_locator, make_locator
from .rules_structural import run_structural_rules

NIH_REF = {
    "url": "https://beta.nih.gov/funding/preparing-your-application/preparing-research-plan/rigorous-study-design-and-transparent-reporting",
    "title": "NIH — Rigorous Study Design and Transparent Reporting",
    "verified": True,
    "doi": None,
}


def run_rules(
    design: dict[str, Any],
    *,
    source_file: str,
    media_type: str | None,
    full_text: str,
    limited_audit: bool = False,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    fid = 1
    qid = 1

    def next_f() -> str:
        nonlocal fid
        s = f"F{fid:02d}"
        fid += 1
        return s

    def next_q() -> str:
        nonlocal qid
        s = f"Q{qid:02d}"
        qid += 1
        return s

    goal = design.get("research_goal_level") or "unspecified"
    hits = design.get("_hits") or {}
    controls = design.get("controls") or []
    replication = design.get("replication") or {}
    outcomes = design.get("outcomes") or []
    claims = design.get("claims") or []

    has_blank = any(c.get("type") in ("blank", "reference", "negative") and c.get("present") for c in controls)
    has_solvent = any(c.get("type") in ("solvent", "vehicle") and c.get("present") for c in controls)
    # Group-based reference (B0/B1 etc.) — never false-positive missing blank
    groups = design.get("groups") or []
    group_blob = " ".join(f"{g.get('name','')} {g.get('treatment','')} {g.get('control_role_hint','')}" for g in groups)
    has_group_reference = bool(
        re.search(r"空白|裸|参照|基础涂层|B0\b|未处理|blank|reference", group_blob, re.I)
    )
    has_blankish = has_blank or has_group_reference

    has_ros = any("ROS" in (o.get("text") or "") for o in outcomes) or bool(hits.get("ros"))
    has_process = any(
        any(k in (o.get("text") or "") for k in ("转化", "转移", "生长", "过程", "频率", "表达", "存活", "附着"))
        for o in outcomes
    )
    mechanism_lang = bool(hits.get("mechanism")) or any(
        ("介导" in c or "mechanism" in c.lower() or "主要通过" in c) for c in claims if isinstance(c, str)
    )
    has_intervention = bool(
        re.search(
            r"(ROS\s*清除|抗氧化|NAC|抑制剂|阻断|挽救|rescue|scavenger|knockdown|过表达抑制)",
            full_text,
            re.I,
        )
    )

    # --- Structural hard gates first ---
    structural = run_structural_rules(
        design,
        source_file=source_file,
        media_type=media_type,
        full_text=full_text,
        id_start=fid,
    )
    findings.extend(structural["findings"])
    fid = structural["next_fid"]
    has_blankish = has_blankish or structural.get("has_blankish_control", False)
    for q in structural.get("clarifying_questions") or []:
        # renumber into global Q sequence
        q = dict(q)
        q["id"] = next_q()
        questions.append(q)

    # --- Legacy mechanism gap (fixtures) — only if no structural corr/mechanism already ---
    if (mechanism_lang or goal == "mechanism_causal") and not any(
        f.get("rule_id") in ("structural_corr_not_cause",) for f in findings
    ):
        if not has_intervention and (has_ros or "介导" in full_text or "mechanism" in full_text.lower()):
            # Avoid double-counting when structural already covered 润湿性/相关
            if re.search(r"介导|ROS|mechanism", full_text, re.I) and not re.search(r"润湿性|接触角", full_text):
                loc_rq = _loc_from_field(design, "research_question", source_file, media_type)
                findings.append({
                    "id": next_f(),
                    "dimension": "claim_evidence",
                    "severity": "blocker" if goal == "mechanism_causal" else "high",
                    "category": "confirmed" if goal == "mechanism_causal" or mechanism_lang else "needs_info",
                    "title": "机制/介导主张缺乏干预证据",
                    "locations": _hit_locs(hits, "mechanism", source_file, media_type) or [loc_rq],
                    "why_invalidates": (
                        "仅凭处理后指标同步变化不能证明介导；按当前设计最多支持伴随变化或处理效应。"
                    ),
                    "fix": (
                        "若目标仅为处理效应：下调主张表述。若必须证明介导：增加最小干预并设对应溶剂对照。"
                    ),
                    "evidence_class": "实验设计方法学原则",
                    "evidence_refs": [NIH_REF],
                    "estimated_burden": "medium",
                    "hard_error": True,
                    "rule_id": "legacy_mechanism_gap",
                })

    if goal == "exploratory":
        for f in findings:
            if f["dimension"] == "claim_evidence" and "介导" in f["title"]:
                f["severity"] = "medium"
                f["category"] = "suggestion"
                f["hard_error"] = False

    # --- Controls: blank only if truly missing (no B0/B1/reference) ---
    if not has_blankish:
        findings.append({
            "id": next_f(),
            "dimension": "controls",
            "severity": "high",
            "category": "confirmed",
            "title": "缺少空白/未处理对照",
            "locations": [_control_loc(controls, "blank", source_file, media_type)],
            "why_invalidates": "无法区分处理效应与基线漂移或测定背景。",
            "fix": "增加与处理组平行的空白对照（除处理因素外其余条件一致）。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": True,
            "rule_id": "legacy_missing_blank",
        })

    mentions_dmso = bool(re.search(r"DMSO|甲醇|丙酮|solvent|溶剂溶解|助溶剂", full_text, re.I))
    # Skip legacy solvent if structural already flagged
    if mentions_dmso and not has_solvent and not any(
        f.get("rule_id") == "structural_solvent_confound" for f in findings
    ):
        findings.append({
            "id": next_f(),
            "dimension": "controls",
            "severity": "high",
            "category": "confirmed",
            "title": "使用溶剂但缺少匹配的溶剂对照",
            "locations": _find_text_loc(full_text, source_file, media_type, "溶剂")
            or [_control_loc(controls, "solvent", source_file, media_type)],
            "why_invalidates": "溶剂本身可能改变终点；处理效应可能与溶剂效应混杂。",
            "fix": "增加溶剂体积与处理组匹配的溶剂对照；各组溶剂终浓度一致。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": True,
            "rule_id": "legacy_missing_solvent",
        })

    # --- Pseudoreplication legacy (needs_info) if structural did not already confirm ---
    if not any(f.get("dimension") == "pseudoreplication" for f in findings):
        if replication.get("ambiguous_parallel"):
            loc = (replication.get("locations") or [fallback_locator(source_file, media_type)])[0]
            findings.append({
                "id": next_f(),
                "dimension": "pseudoreplication",
                "severity": "high",
                "category": "needs_info",
                "title": "「平行/重复」独立性未写清",
                "locations": [loc],
                "why_invalidates": "若平行为同一实验单位的技术重复，直接作独立样本会低估变异。",
                "fix": "明确实验单位：独立批次/独立生物重复 vs 技术复孔；统计仅对独立单位推断。",
                "evidence_class": "实验设计方法学原则",
                "evidence_refs": [NIH_REF],
                "estimated_burden": "unknown",
                "hard_error": False,
                "rule_id": "legacy_ambiguous_parallel",
            })
            questions.append({
                "id": next_q(),
                "question": "请确认：文中的「平行/重复」是独立实验批次（或独立生物重复），还是同一批样品的技术平行/复孔？",
                "blocks_dimensions": ["pseudoreplication", "statistics"],
                "priority": "critical",
                "context_quote": replication.get("text") or "平行",
                "locations": [loc],
            })
        elif not replication.get("text"):
            findings.append({
                "id": next_f(),
                "dimension": "pseudoreplication",
                "severity": "medium",
                "category": "needs_info",
                "title": "未说明重复与实验单位",
                "locations": [fallback_locator(source_file, media_type, "（未找到重复描述）")],
                "why_invalidates": "无法判断统计推断单位，组间比较可能无效。",
                "fix": "补充独立生物重复数量、技术重复层级与实验单位定义。",
                "evidence_class": "实验设计方法学原则",
                "evidence_refs": [NIH_REF],
                "estimated_burden": "low",
                "hard_error": False,
                "rule_id": "legacy_missing_replication",
            })

    if not (design.get("statistical_plan") or "").strip() and not any(
        f.get("dimension") == "statistics" for f in findings
    ):
        findings.append({
            "id": next_f(),
            "dimension": "statistics",
            "severity": "medium",
            "category": "needs_info" if goal != "exploratory" else "suggestion",
            "title": "未预先说明统计分析计划",
            "locations": [fallback_locator(source_file, media_type, "（未找到统计计划）")],
            "why_invalidates": "事后选检验方式会削弱结论可信度。",
            "fix": "预先写明比较关系、统计单位、拟用模型/检验及多重比较策略。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "none",
            "hard_error": False,
            "rule_id": "legacy_missing_stats",
        })

    if limited_audit:
        findings.append({
            "id": next_f(),
            "dimension": "reproducibility",
            "severity": "medium",
            "category": "needs_info",
            "title": "关键设计信息仍缺失：本次为有限审查",
            "locations": [fallback_locator(source_file, media_type, "（解析警告/未补表）")],
            "why_invalidates": "表格或关键字段未补全时，不得将本报告视为全面审查。",
            "fix": "补充分组表、对照与重复定义后重新审查。",
            "evidence_class": "用户方案内矛盾",
            "evidence_refs": [],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "limited_audit",
        })

    # Per-hypothesis Claim–Evidence (replaces generic one-liner)
    ce_map = build_claim_evidence_map(
        design,
        source_file=source_file,
        media_type=media_type,
        full_text=full_text,
        findings=findings,
    )

    questions = sorted(
        questions,
        key=lambda q: {"critical": 0, "high": 1, "normal": 2}.get(q["priority"], 3),
    )[:5]

    # Renumber finding ids sequentially for this pass (LLM merge may renumber again)
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F{i:02d}"

    return {
        "findings": findings,
        "clarifying_questions": questions,
        "claim_evidence_map": ce_map,
    }


def _hit_locs(hits: dict, key: str, source_file: str, media_type: str | None) -> list[dict[str, Any]]:
    items = hits.get(key) or []
    if not items:
        return [fallback_locator(source_file, media_type)]
    return [items[0]["locator"]]


def _loc_from_field(design: dict, field: str, source_file: str, media_type: str | None) -> dict[str, Any]:
    meta = design.get("field_meta") or {}
    locs = meta.get(f"{field}_locations") or []
    if locs:
        return locs[0]
    text = design.get(field) or ""
    if text:
        return make_locator(source_file, str(text)[:200], media_type=media_type)
    return fallback_locator(source_file, media_type)


def _control_loc(controls: list, ctype: str, source_file: str, media_type: str | None) -> dict[str, Any]:
    for c in controls:
        if c.get("type") == ctype:
            locs = c.get("locations") or []
            if locs:
                return locs[0]
            if c.get("quote"):
                return make_locator(source_file, c["quote"], media_type=media_type)
    return fallback_locator(source_file, media_type, f"（对照类型 {ctype}）")


def _find_text_loc(
    full_text: str,
    source_file: str,
    media_type: str | None,
    needle: str,
) -> list[dict[str, Any]]:
    idx = full_text.upper().find(needle.upper())
    if idx < 0:
        return []
    snippet = full_text[max(0, idx - 20) : idx + 40]
    return [make_locator(source_file, snippet, media_type=media_type, char_start=idx, char_end=idx + len(needle))]
