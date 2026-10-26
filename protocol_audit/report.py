"""Assemble AuditReport 0.2.1."""
from __future__ import annotations

from typing import Any

from .claim_evidence import build_claim_evidence_map
from .llm_review import llm_scientific_review, merge_findings
from .locators import fallback_locator, make_locator
from .optimizer_a import build_group_table, plan_a
from .rules import run_rules
from .rules_structural import adjust_extrapolation_severity

CONTROL_TYPE_OK = {
    "blank", "solvent", "vehicle", "positive", "negative",
    "co_exposure", "recipient_preexposure", "plasmid_preexposure",
    "heat_inactivated", "other",
}


def assemble_report(
    *,
    design: dict[str, Any],
    preview: dict[str, Any],
    source_file: str,
    media_type: str | None,
    full_text: str,
    discipline: str = "auto",
    confirmed: bool = True,
    confirmed_at: str | None = None,
    confirmation_notes: str = "",
    use_llm_review: bool = False,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    limited = bool(preview.get("limited_audit_recommended"))
    unparsed = list(preview.get("unparsed_assets") or [])
    warnings = list(preview.get("parse_warnings") or [])

    rules_out = run_rules(
        design,
        source_file=source_file,
        media_type=media_type,
        full_text=full_text,
        limited_audit=limited,
    )
    findings = adjust_extrapolation_severity(rules_out["findings"], full_text)
    questions = rules_out["clarifying_questions"]
    ce_map = rules_out["claim_evidence_map"]

    llm_meta = design.get("_llm_meta") or {}
    review_meta = None
    review_coverage = None
    review_status = "rules_only"
    # Tag rule findings origin before merge
    for f in findings:
        f.setdefault("origin", "rule")
        f.setdefault("source", "rule")
    if use_llm_review:
        # Always compute coverage for transparency (even if LLM later fails)
        from .review_windows import build_review_windows
        _wins, _cov = build_review_windows(full_text or "")
        review_coverage = _cov.to_dict()
        rev = llm_scientific_review(
            design,
            source_file=source_file,
            media_type=media_type,
            full_text=full_text,
            provider=llm_provider,
        )
        review_meta = rev.get("llm_meta") or {}
        review_status = review_meta.get("review_status") or (
            "complete" if review_meta.get("ok") else (
                "partial" if rev.get("partial_review") or review_meta.get("partial_review") else "failed"
            )
        )
        if rev.get("review_coverage"):
            review_coverage = rev.get("review_coverage")
        llm_findings = rev.get("findings") or []
        for f in llm_findings:
            f.setdefault("origin", "llm_review")
            f.setdefault("source", "llm_review")
        # Merge; if review failed completely with zero LLM findings, keep rules and mark partial/failed
        findings = merge_findings(findings, llm_findings)
        findings = adjust_extrapolation_severity(findings, full_text)
        # rebuild CE with merged findings (keep rule themes via titles)
        ce_map = build_claim_evidence_map(
            design,
            source_file=source_file,
            media_type=media_type,
            full_text=full_text,
            findings=findings,
        )

    # Plan A needs rule_id for mapping — run before stripping internal keys
    group_table = build_group_table(design)
    optimizer = plan_a(design, findings, group_table)

    # Strip non-schema keys from findings; KEEP duplicate relation + origin (V0.1.3.3)
    DROP_KEYS = {"rule_id", "source", "review_window_id", "review_window_range"}
    KEEP_EXTRA = (
        "related_claim_ids",
        "duplicate_of",
        "duplicate_group",
        "duplicate_reason",
        "duplicate_relation",
        "origin",
    )
    clean_findings = []
    origin_counts = {"llm_review": 0, "rule": 0, "partial_fallback": 0, "other": 0}
    for f in findings:
        nf = {k: v for k, v in f.items() if k not in DROP_KEYS}
        # Map internal source → origin if needed
        origin = f.get("origin") or (
            "llm_review" if f.get("source") == "llm_review" or f.get("rule_id") == "llm_review"
            else "rule"
        )
        if review_status in ("partial", "failed") and origin == "llm_review":
            # LLM findings recovered under partial review still tagged llm_review;
            # absence of LLM findings under failed review means rules-only output.
            pass
        nf["origin"] = origin if origin in ("llm_review", "rule", "partial_fallback") else "rule"
        origin_counts[nf["origin"]] = origin_counts.get(nf["origin"], 0) + 1
        for k in KEEP_EXTRA:
            if k in f and f.get(k) is not None and k != "origin":
                nf[k] = f[k]
            elif k in nf and nf[k] is None and k.startswith("duplicate"):
                nf.pop(k, None)
        clean_findings.append(nf)
    findings = clean_findings

    # Sanitize CE rows: keep only schema-known + extended fields; ensure required
    ce_rows = []
    for r in ce_map.get("rows") or []:
        row = {
            "id": r.get("id") or "CE01",
            "claim": r.get("claim") or "",
            "evidence_from_design": r.get("evidence_from_design") or "",
            "judgment": r.get("judgment") or "",
            "gap": r.get("gap") if r.get("gap") is not None else "",
        }
        for opt in ("aligned_goal_levels", "locations", "hypothesis_id", "planned_comparison",
                    "endpoints", "evidence_needed", "design_supports", "fix_hint", "row_kind"):
            if opt in r and r[opt] is not None:
                row[opt] = r[opt]
        if "row_kind" not in row:
            row["row_kind"] = "scope_note" if row.get("hypothesis_id") == "SCOPE" else "claim"
        ce_rows.append(row)
    ce_map = {"rows": ce_rows, "notes": ce_map.get("notes") or []}

    identification = _build_identification(design, source_file, media_type)
    discipline_resolved = _resolve_discipline(discipline, full_text)

    summary = _build_summary(findings, questions, ce_map, limited)
    boundary = _boundary_note(unparsed, limited, discipline_resolved, llm_meta, review_meta, design, review_coverage, review_status=review_status, origin_counts=origin_counts)
    coverage = _coverage_note(preview, review_coverage)

    goal = design.get("research_goal_level") or "unspecified"
    goal_source = design.get("research_goal_level_source") or "default"
    if goal_source not in ("user", "inferred", "default"):
        goal_source = "default"

    report: dict[str, Any] = {
        "schema_version": "0.2.1",
        "discipline_resolved": discipline_resolved,
        "boundary_note": boundary,
        "research_goal_level": goal,
        "research_goal_level_source": goal_source,
        "ingest_manifest": {
            "source_file": source_file,
            "media_type": media_type,
            "parse_warnings": warnings,
            "blocks_count": len(preview.get("ingested_blocks") or []),
            "tables_count": int(preview.get("tables_parsed_count") or 0),
            "unparsed_assets": unparsed,
        },
        "design_confirmation": {
            "status": "confirmed" if confirmed else "pending",
            "confirmed_at": confirmed_at if confirmed else None,
            "notes": confirmation_notes or "",
        },
        "summary": summary,
        "identification": identification,
        "claim_evidence_map": ce_map,
        "clarifying_questions": questions,
        "findings": findings,
        "optimizer": optimizer,
        "group_table": group_table,
        "literature_hints": [],
        "reverse_review": {
            "enabled": False,
            "status": "deferred_v0_2",
            "preview_strongest_claim": summary.get("strongest_supported_claim") or "",
            "note": "完整逆向审查延后到 V0.2；此处仅提供 strongest_supported_claim 预览。",
        },
        "privacy_applied": {
            "public_literature_search_used": False,
            "note": "V0.1 骨架默认不触发公开文献检索",
        },
        "limited_audit": limited,
        "coverage_note": coverage,
    }
    # Non-schema debug sidecar keys are NOT included (additionalProperties may be false on root)
    return report


def _map_control_type(t: str) -> str:
    t = (t or "other").lower()
    if t in CONTROL_TYPE_OK:
        return t
    if t in ("reference", "baseline", "control"):
        return "negative"
    return "other"


def _build_identification(design: dict[str, Any], source_file: str, media_type: str | None) -> dict[str, Any]:
    meta = design.get("field_meta") or {}
    rq = {
        "text": design.get("research_question") or "",
        "status": meta.get("research_question_status") or ("stated" if design.get("research_question") else "missing"),
        "locations": meta.get("research_question_locations") or [],
    }
    hyps = design.get("hypotheses") or []
    hyp_text = "；".join(hyps[:5]) if hyps else ""
    hypothesis = {
        "text": hyp_text,
        "status": meta.get("hypothesis_status") or ("stated" if hyps else "missing"),
        "locations": meta.get("hypothesis_locations") or [],
    }
    groups = []
    for g in design.get("groups") or []:
        groups.append({
            "name": g.get("name") or "",
            "treatment": g.get("treatment") or "",
            "n_claimed": g.get("n_claimed"),
            "status": g.get("status") or "inferred",
            "quote": g.get("quote") or "",
            "locations": g.get("locations") or [],
        })
    controls = []
    for c in design.get("controls") or []:
        controls.append({
            "type": _map_control_type(c.get("type") or "other"),
            "label": c.get("label"),
            "present": bool(c.get("present")),
            "excludes_alternative": c.get("excludes_alternative") or "",
            "status": c.get("status") or "missing",
            "quote": c.get("quote") or "",
            "locations": c.get("locations") or [],
        })
    endpoints = []
    for e in design.get("outcomes") or []:
        endpoints.append({
            "text": e.get("text") if isinstance(e, dict) else str(e),
            "status": e.get("status", "stated") if isinstance(e, dict) else "stated",
            "locations": e.get("locations", []) if isinstance(e, dict) else [],
        })
    rep = design.get("replication") or {}
    replication = {
        "text": rep.get("text") if isinstance(rep, dict) else str(rep or ""),
        "status": (rep.get("status") if isinstance(rep, dict) else None) or "missing",
        "locations": (rep.get("locations") if isinstance(rep, dict) else None) or [],
    }
    # status enum
    if replication["status"] not in ("stated", "inferred", "missing", "contradictory", "recommended"):
        replication["status"] = "inferred"
    stats = {
        "text": design.get("statistical_plan") or "",
        "status": design.get("statistics_status") or ("stated" if design.get("statistical_plan") else "missing"),
        "locations": design.get("statistics_locations") or [],
    }
    if stats["status"] not in ("stated", "inferred", "missing", "contradictory", "recommended"):
        stats["status"] = "stated"
    claims = []
    for c in design.get("claims") or []:
        claims.append({
            "text": c if isinstance(c, str) else str(c),
            "status": "stated",
            "locations": [],
        })
    unit = {
        "text": design.get("experimental_unit") or "",
        "status": meta.get("experimental_unit_status") or ("stated" if design.get("experimental_unit") else "missing"),
        "locations": meta.get("experimental_unit_locations") or [],
    }
    gaps = []
    for name, field in (
        ("research_question", rq),
        ("hypothesis", hypothesis),
        ("replication", replication),
        ("statistics", stats),
        ("experimental_unit", unit),
    ):
        if field["status"] in ("missing", "contradictory"):
            gaps.append(name)
    if not groups:
        gaps.append("groups")
    if not any(c.get("present") for c in controls):
        gaps.append("controls")

    return {
        "research_question": rq,
        "hypothesis": hypothesis,
        "independent_vars": [],
        "dependent_vars": endpoints[:],
        "experimental_unit": unit,
        "groups": groups,
        "controls": controls,
        "endpoints": endpoints,
        "replication": replication,
        "statistics": stats,
        "claims": claims,
        "gaps": gaps,
    }


def _build_summary(
    findings: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    ce_map: dict[str, Any],
    limited: bool,
) -> dict[str, Any]:
    blocker = sum(1 for f in findings if f.get("severity") == "blocker")
    high = sum(1 for f in findings if f.get("severity") == "high")
    confirmed = sum(1 for f in findings if f.get("category") == "confirmed")
    needs_info = sum(1 for f in findings if f.get("category") == "needs_info")
    suggestion = sum(1 for f in findings if f.get("category") == "suggestion")

    crit_q = [q for q in questions if q.get("priority") == "critical"]
    if limited:
        verdict = "insufficient_info"
    elif crit_q:
        verdict = "awaiting_clarification"
    elif blocker:
        verdict = "needs_redesign"
    elif high or confirmed:
        verdict = "ready_with_fixes"
    else:
        verdict = "ready_with_fixes"

    strongest = "在澄清与最小修改前，不宜把相关或短周期结果写成机制/工程定论。"
    for row in ce_map.get("rows") or []:
        if row.get("design_supports") == "yes":
            strongest = f"相对最稳的主张：" + (row.get("claim") or "")[:160]
            break

    one = (
        f"确认问题 {confirmed}，待核实 {needs_info}，建议 {suggestion}；"
        + ("关键信息不足，有限审查。" if limited else ("请先回答关键追问。" if crit_q else "见 Plan A 最小修改。"))
    )[:240]

    return {
        "verdict": verdict,
        "blocker_count": blocker,
        "high_count": high,
        "confirmed_count": confirmed,
        "needs_info_count": needs_info,
        "suggestion_count": suggestion,
        "one_liner": one,
        "strongest_supported_claim": strongest,
    }


def _resolve_discipline(discipline: str, full_text: str) -> str:
    if discipline in ("environmental", "biology", "chemistry"):
        return discipline
    t = full_text.lower()
    if any(k in t for k in ("污染物", "环境", "污泥", "水体", "6ppd", "土壤", "生物膜", "防污", "水槽")):
        return "environmental"
    if any(k in t for k in ("细胞", "小鼠", "基因", "质粒", "细菌", "pcr")):
        return "biology"
    if any(k in t for k in ("合成", "催化", "色谱", "nmr", "反应产率")):
        return "chemistry"
    return "environmental"


def _boundary_note(unparsed, limited, discipline, llm_meta, review_meta, design, review_coverage=None, review_status="rules_only", origin_counts=None) -> str:
    parts = [f"学科边界：本次按 {discipline} 规则审查（环境/生物/化学）。"]
    if unparsed:
        kinds = ", ".join(sorted({u.get("asset_type", "other") for u in unparsed}))
        parts.append(f"存在未解析资产（{kinds}），审查未声称覆盖这些资产。")
    if limited:
        parts.append("关键设计信息缺失或扫描表未补：本次为有限审查，不得视为全面审查。")
    if review_coverage and not review_coverage.get("comprehensive", True):
        if review_coverage.get("methods_detected") and not review_coverage.get("methods_included"):
            parts.append("方法段未充分进入审查输入：不得声称全面审查（见 coverage_note / review_coverage）。")
        elif review_coverage.get("truncated"):
            parts.append("审查输入窗口未覆盖全文：不得声称全面审查（见 coverage_note / review_coverage）。")
        else:
            parts.append("审查覆盖不完整：不得声称全面审查（见 coverage_note / review_coverage）。")
    elif review_coverage and review_coverage.get("truncated"):
        parts.append("审查输入存在截断/遗漏片段，覆盖范围见 coverage_note。")
    # Review reliability status (V0.1.3.3) — never pretend complete LLM review after truncation
    if review_status == "partial":
        parts.append(
            "科学审查为部分审查（存在窗口截断/扩容重试仍失败）："
            "不得将本次报告视为完整 LLM 审查；findings.origin 区分规则与 LLM 来源。"
        )
    elif review_status == "failed":
        parts.append(
            "科学审查 LLM 调用失败或截断后仍无法解析："
            "本报告 findings 以规则为主，禁止伪装为完整 LLM 审查。"
        )
    oc = origin_counts or {}
    if oc:
        parts.append(
            f"findings 来源统计：llm_review={oc.get('llm_review', 0)}，"
            f"rule={oc.get('rule', 0)}，partial_fallback={oc.get('partial_fallback', 0)}。"
        )
    eng = [
        "引擎：V0.1.3.3 结构规则/后处理 + 方法优先审查窗 + 审查截断扩容重试"
        "（科学 Prompt 仍冻结于 V0.1.2；含 0.1.2.1 解析可靠性与 0.1.3.3 审查可靠性；"
        "外推严重度与软去重收窄；CE 限制句 scope_note；提取/窗口策略为独立技术版本）"
    ]
    if design.get("_llm_extract"):
        eng.append("+ LLM 解析")
    if review_meta and review_meta.get("ok") and review_status == "complete":
        eng.append("+ LLM 科学审查（完整）")
    elif review_status == "partial":
        eng.append("+ LLM 科学审查（部分，见 review_status）")
    elif review_status == "failed":
        eng.append("（解析可用 LLM，科学审查未完整成功）")
    elif llm_meta and llm_meta.get("ok"):
        eng.append("（解析用 LLM，审查以规则为主）")
    if llm_meta and llm_meta.get("fallback"):
        eng.append("；LLM 解析回退至启发式")
    parts.append("".join(eng) + "。不得将模拟输出冒充实测。")
    return "".join(parts)


def _coverage_note(preview: dict[str, Any], review_coverage: dict[str, Any] | None = None) -> str:
    n = len(preview.get("ingested_blocks") or [])
    manual = len(preview.get("manual_supplements") or [])
    unparsed = len(preview.get("unparsed_assets") or [])
    base = f"已解析块 {n}；手动补充 {manual}；未解析资产 {unparsed}。"
    if not review_coverage:
        return base
    from .review_windows import ReviewCoverage
    # accept dict
    try:
        rc = ReviewCoverage(**{k: v for k, v in review_coverage.items() if k in ReviewCoverage.__dataclass_fields__})
        return base + " " + rc.summary_zh()
    except Exception:
        return base + f" review_coverage: comprehensive={review_coverage.get('comprehensive')} truncated={review_coverage.get('truncated')} methods_included={review_coverage.get('methods_included')}."
