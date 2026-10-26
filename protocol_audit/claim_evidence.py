"""Per-hypothesis Claim–Evidence Mapping (domain-agnostic; no H-id templates)."""
from __future__ import annotations

import re
from typing import Any

from .locators import fallback_locator, make_locator


def build_claim_evidence_map(
    design: dict[str, Any],
    *,
    source_file: str,
    media_type: str | None,
    full_text: str,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    findings = findings or []
    rows: list[dict[str, Any]] = []
    hyps = design.get("hypotheses_structured") or []
    # Defensive: only dict hypotheses; strings may be TOC noise from extract merge
    hyps = [h for h in hyps if isinstance(h, dict) and ((h.get("text") or h.get("expected_conclusion") or "").strip())]
    if not hyps:
        hyps = _parse_hypotheses_from_text(design, full_text, source_file, media_type)

    ceid = 1
    covered_kinds: set[str] = set()
    for h in hyps:
        if not isinstance(h, dict):
            continue
        hid = h.get("id") or f"H{ceid}"
        text = (h.get("text") or "").strip()
        expected = (h.get("expected_conclusion") or "").strip()
        if not text and not expected:
            continue
        locs = h.get("locations") or [fallback_locator(source_file, media_type)]
        claim = expected or text
        kind = _classify_claim_kind(text, expected)
        covered_kinds.add(kind)
        comparison = _planned_comparison(kind, text, expected, design, full_text)
        endpoints = _endpoints_for(hid, text, design, full_text)
        needed, supports, gap, fix = _gap_from_findings(
            kind, text, expected, design, findings, full_text
        )
        judgment = {
            "yes": "当前设计可支持该主张",
            "partial": "当前设计仅部分支持该主张",
            "no": "当前设计不能支持该主张",
        }[supports]
        rows.append({
            "id": f"CE{ceid:02d}",
            "claim": f"{hid}：{claim}"[:300],
            "evidence_from_design": f"比较：{comparison}；指标：{endpoints}"[:400],
            "judgment": judgment,
            "gap": gap,
            "aligned_goal_levels": _goal_levels_for(kind, text),
            "locations": locs[:3],
            "hypothesis_id": hid,
            "planned_comparison": comparison,
            "endpoints": [e.strip() for e in endpoints.split("；") if e.strip()],
            "evidence_needed": needed,
            "design_supports": supports,
            "fix_hint": fix,
            "row_kind": "claim",
        })
        ceid += 1

    # Extrapolation vs scope notes (V0.1.3.3):
    # Research limitation / applicability statements must NOT become EXTRAP claims with design_supports=no.
    scope_notes = _collect_scope_notes(design, full_text, source_file, media_type)
    for note in scope_notes:
        rows.append({
            "id": f"CE{ceid:02d}",
            "claim": note["text"][:300],
            "evidence_from_design": "方案已声明结论适用范围/限制，属边界说明而非待检验的外推主张",
            "judgment": "已声明研究边界（scope_note），不作为外推主张的支持/反对证据",
            "gap": "",
            "aligned_goal_levels": ["exploratory"],
            "locations": note.get("locations") or [fallback_locator(source_file, media_type)],
            "hypothesis_id": "SCOPE",
            "planned_comparison": "不适用（适用范围声明）",
            "endpoints": [],
            "evidence_needed": "无（边界说明）",
            "design_supports": "yes",
            "fix_hint": "保持限制声明；若另有肯定性工程/长期主张，另起 EXTRAP 行审查",
            "row_kind": "scope_note",
        })
        ceid += 1

    # Extrapolation row only for affirmative over-claims (not scope limitations)
    if "extrapolation" not in covered_kinds and _has_extrapolation_claim(design, full_text):
        claim_text = _extrapolation_claim_text(design, full_text)
        if claim_text and not _is_scope_limitation(claim_text):
            supports = "no"
            gap = "短周期/简化工况的实验室结果不足以直接支撑长期或工程运行主张"
            fix = "将应用表述降为初步实验室证据；补相关工况、更长周期或现场/中试验证后再谈工程依据"
            loc = _snip(full_text, source_file, media_type, "工程") or _snip(
                full_text, source_file, media_type, "连续运行"
            ) or [fallback_locator(source_file, media_type)]
            ep = _endpoints_for("EXTRAP", claim_text, design, full_text)
            rows.append({
                "id": f"CE{ceid:02d}",
                "claim": claim_text[:300],
                "evidence_from_design": f"比较：实验室短期/简化体系 → 工程或连续运行主张；指标：{ep}"[:400],
                "judgment": "当前设计不能支持该主张",
                "gap": gap,
                "aligned_goal_levels": ["generalizability"],
                "locations": loc,
                "hypothesis_id": "EXTRAP",
                "planned_comparison": "实验室短期结果 → 工程/连续运行性能",
                "endpoints": [e.strip() for e in ep.split("；") if e.strip()],
                "evidence_needed": "更长周期、相关工况或现场/中试验证",
                "design_supports": supports,
                "fix_hint": fix,
                "row_kind": "claim",
            })
            ceid += 1

    if not rows:
        rows.append({
            "id": "CE01",
            "claim": design.get("research_question") or "（未解析到明确假设）",
            "evidence_from_design": "分组或假设信息不足",
            "judgment": "当前设计不能支持该主张",
            "gap": "请补充可检验的假设与对应比较",
            "aligned_goal_levels": ["exploratory"],
            "locations": [fallback_locator(source_file, media_type)],
            "hypothesis_id": "UNKNOWN",
            "planned_comparison": "unknown",
            "endpoints": [],
            "evidence_needed": "明确假设、比较与终点",
            "design_supports": "no",
            "fix_hint": "在方案中写出可检验假设",
        })

    goal = design.get("research_goal_level") or "unspecified"
    notes = [
        f"当前 research_goal_level={goal}（未在证据不足时自动升为 mechanism_causal）。",
        "Claim–Evidence 按假设分行；比较句由分组/因素/主张类型生成，禁止按 H 编号套领域模板。",
        "实验单位重复 ≠ 独立制备批次；单批次不自动升为 confirmed blocker，跨批次推广须单独论证。",
        "适用范围/限制声明记为 scope_note，不作为 EXTRAP 主张的支持或反对证据。",
    ]
    return {"rows": rows, "notes": notes}


def _classify_claim_kind(text: str, expected: str) -> str:
    t = f"{text} {expected}"
    if re.search(r"协同|交互|联用", t):
        return "synergy"
    if re.search(r"机制|介导|主要通过|主要来源|主导机制|特异性结合", t):
        return "mechanism"
    if re.search(r"工程|长期|连续运行|外推|投用|应用依据|主要依据", t):
        return "extrapolation"
    return "treatment_effect"


def _group_summary(design: dict[str, Any]) -> str:
    parts = []
    for g in design.get("groups") or []:
        name = (g.get("name") or "").strip()
        treat = (g.get("treatment") or "").strip()
        if name or treat:
            parts.append(f"{name}:{treat}" if name and treat and name != treat else (name or treat))
    return "；".join(parts[:8]) if parts else ""


def _factor_summary(design: dict[str, Any], needles: list[str] | None = None) -> str:
    parts = []
    for f in design.get("factors") or []:
        name = f.get("name") or ""
        levels = f.get("levels") or []
        blob = name + " " + " ".join(str(x) for x in levels)
        if needles and not any(n.lower() in blob.lower() for n in needles):
            continue
        lv = "/".join(str(x) for x in levels[:6])
        parts.append(f"{name}[{lv}]" if lv else name)
    return "；".join(parts[:6]) if parts else ""


def _planned_comparison(
    kind: str, text: str, expected: str, design: dict[str, Any], full_text: str
) -> str:
    """Build comparison string from design fields — never from hypothesis id alone."""
    groups = _group_summary(design)
    t = f"{text} {expected}"

    if kind == "synergy":
        factors = _factor_summary(design) or "方案中的多因素水平"
        return f"析因/联用比较（因素：{factors}；分组：{groups or '见原文'}）"

    if kind == "mechanism":
        return (
            f"处理效应比较（{groups or '处理 vs 基线'}）+ 机制相关表征/操纵；"
            "机制主张需能排除替代解释，而非仅共变"
        )

    if kind == "extrapolation":
        return "实验室短期/简化体系结果 → 工程或连续运行性能主张"

    # treatment_effect: try to align with hypothesis keywords to pick factors
    needles: list[str] = []
    if re.search(r"pH|酸碱", t):
        needles += ["pH", "缓冲"]
    if re.search(r"共存|竞争|选择性|腐殖|碳酸", t):
        needles += ["共存", "Ca", "Mg", "HCO", "腐殖"]
    if re.search(r"再生|循环|碱洗", t):
        needles += ["再生", "轮"]
    if re.search(r"剂量|投加", t):
        needles += ["投加", "剂量"]
    if re.search(r"UV|紫外", t):
        needles += ["UV", "紫外"]
    if re.search(r"颗粒|涂层|附着", t):
        needles += ["颗粒", "涂层", "UV"]
    factors = _factor_summary(design, needles or None)
    if groups and factors:
        return f"组间比较（{groups}）；相关因素：{factors}"
    if groups:
        return f"组间比较（{groups}）"
    if factors:
        return f"按因素水平比较（{factors}）"
    # last resort: paraphrase claim into a comparison ask
    return "（由假设文本与分组推断的组间比较；请核对原文因素水平）"


def _endpoints_for(hid: str, text: str, design: dict[str, Any], full_text: str) -> str:
    endpoints: list[str] = []
    for o in design.get("outcomes") or []:
        ot = (o.get("text") or "").strip()
        if not ot:
            continue
        supports = o.get("supports_claims") or []
        if supports and hid not in supports and hid != "EXTRAP":
            # still include if few outcomes overall
            if len(design.get("outcomes") or []) > 4:
                continue
        endpoints.append(ot)
    if not endpoints:
        for o in design.get("outcomes") or []:
            if o.get("text"):
                endpoints.append(o["text"])
    if not endpoints:
        # soft fallbacks from text — domain-neutral cues only when present in THIS protocol
        if re.search(r"除磷|磷酸|吸附量|q[ₑeₜt]", full_text):
            endpoints.append("除磷率/吸附量")
        if re.search(r"附着|生物量|OD\s*\d+", full_text):
            endpoints.append("附着生物量")
        if re.search(r"接触角|润湿", full_text):
            endpoints.append("接触角/润湿性")
        if re.search(r"XPS|FTIR|SEM", full_text):
            endpoints.append("表面表征（如 XPS/FTIR）")
    return "；".join(dict.fromkeys(e for e in endpoints if e)) or "unknown"


def _relevant_findings(
    kind: str, text: str, findings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pick findings that actually bear on this claim — by dimension/title, not H-id."""
    t = text
    out = []
    for f in findings:
        dim = f.get("dimension") or ""
        title = f.get("title") or ""
        why = f.get("why_invalidates") or ""
        blob = title + why
        rid = f.get("rule_id") or ""
        if kind == "synergy" and (
            dim in ("statistics", "confounding", "pseudoreplication")
            or any(k in blob for k in ("协同", "交互", "析因", "混杂", "伪重复", "容器"))
            or "factorial" in rid or "container" in rid or "pseudo" in rid
        ):
            out.append(f)
        elif kind == "mechanism" and (
            dim in ("claim_evidence", "controls")
            or any(k in blob for k in ("机制", "相关", "表征", "特异性", "工艺"))
            or "corr_not_cause" in rid or "process_blank" in rid
        ):
            out.append(f)
        elif kind == "extrapolation" and (
            dim == "claim_evidence"
            or any(k in blob for k in ("外推", "工程", "再生", "质量", "循环"))
            or "extrap" in rid or "regen" in rid
        ):
            out.append(f)
        elif kind == "treatment_effect":
            matched = False
            if re.search(r"pH|适应性|缓冲", t) and any(k in blob for k in ("缓冲", "pH", "锁定")):
                out.append(f); matched = True
            if re.search(r"共存|选择|竞争", t) and any(k in blob for k in ("共存", "鸡尾酒", "混合投加", "归因", "竞争")):
                out.append(f); matched = True
            if re.search(r"再生|循环", t) and any(k in blob for k in ("再生", "循环", "投加量衰减", "质量衡算")):
                out.append(f); matched = True
            if re.search(r"改性|去除|提高|性能|吸附|附着|降低", t) and any(
                k in blob for k in ("助溶剂", "工艺空白", "工艺步骤", "伪重复", "实验单位", "平行", "容器", "水槽")
            ):
                out.append(f); matched = True
            # volume/kinetics only if claim talks kinetics/time-series OR no more specific match needed
            if any(k in blob for k in ("体积", "动力学", "取样")) and re.search(r"动力学|时间|速率|等温", t):
                out.append(f); matched = True
            if not matched and dim == "pseudoreplication":
                out.append(f)
    # de-dupe by id
    seen = set()
    uniq = []
    for f in out:
        if f.get("id") in seen:
            continue
        seen.add(f.get("id"))
        uniq.append(f)
    return uniq


def _gap_from_findings(
    kind: str,
    text: str,
    expected: str,
    design: dict[str, Any],
    findings: list[dict[str, Any]],
    full_text: str,
) -> tuple[str, str, str, str]:
    """Return needed, supports, gap, fix."""
    rel = _relevant_findings(kind, text + " " + expected, findings)
    alloc = ((design.get("units") or {}).get("allocation_unit") or "").strip()
    unit_label = alloc or "处理分配单位"

    if kind == "mechanism":
        needed = "能排除替代机制的操纵或对照，而非仅相关/表征共变"
        if rel or re.search(r"机制|主要来源|主导|主要通过", text + expected):
            return needed, "no", "相关或表征共变不能证明「主要/主导机制」", (
                "降为相关/伴随描述，或增加机制分离实验（如工艺空白、位点阻断、定量分配）"
            )
        return needed, "partial", "机制主张证据链未闭合", "写清机制检验与替代解释排除"

    if kind == "synergy":
        needed = f"在{unit_label}层面可估计的交互；预定义交互检验；非伪重复 n"
        gaps = []
        fixes = []
        for f in rel:
            gaps.append((f.get("title") or "")[:40])
            if f.get("fix"):
                fixes.append(f["fix"][:80])
        if not gaps:
            # still often unsupported without clear factorial design
            if re.search(r"协同|交互", text + expected):
                return needed, "no", "协同/交互主张缺少可估计交互的设计与预定义检验", (
                    f"在{unit_label}层面保证因素可分与独立重复，并报告交互效应；或删除协同主张"
                )
        return (
            needed,
            "no",
            "；".join(gaps) or "协同/交互在现有结构下不可靠",
            (fixes[0] if fixes else f"补齐{unit_label}层面重复与交互分析，或降级主张"),
        )

    if kind == "extrapolation":
        needed = "更长周期、相关工况或现场/中试验证；若涉及跨批次推广还需独立制备批次证据"
        gap = "短周期/简化工况不足以支撑工程或连续运行主张"
        fix = "收紧为初步实验室证据；外推需补验证"
        batch_fs = [
            f for f in findings
            if (f.get("rule_id") == "structural_single_batch_material")
            or ("单批次" in (f.get("title") or "") or "跨批次" in (f.get("title") or ""))
        ]
        if batch_fs or re.search(r"同一批|单批次", full_text):
            gap += "；单批次材料/菌剂仅支持批次内比较，不能自动支持跨批次推广"
            fix += "；区分批次内效应与跨批次可推广性，必要时补独立制备批次"
        return needed, "no", gap, fix

    # treatment_effect
    needed = "与假设对齐的对照、独立实验单位与终点"
    # Attach single-batch finding when claim implies cross-batch / scale-out
    if re.search(r"推广|工程|田间|放大|规模化|跨批次", text + " " + expected):
        for f in findings:
            if f.get("rule_id") == "structural_single_batch_material" or "单批次" in (f.get("title") or ""):
                if f not in rel:
                    rel.append(f)
    if not rel:
        # check structural rule_ids on all findings for soft partial
        hard = [f for f in findings if f.get("category") == "confirmed" and f.get("severity") in ("blocker", "high")]
        if hard and any(
            any(k in ((f.get("title") or "") + (f.get("why_invalidates") or "")) for k in ("混杂", "伪重复", "体积", "工艺"))
            for f in hard
        ):
            # may still affect — stay partial unless clearly linked
            return needed, "partial", "存在可能影响该主张的设计缺口（见 findings）", "按 findings 做最小必要修改"
        return needed, "partial", "假设未完全映射到可执行比较或证据链仍有缺口", "写清比较组、成功判据与独立单位"

    gaps = []
    fixes = []
    supports = "no"
    for f in rel:
        title = f.get("title") or ""
        gaps.append(title[:60])
        fx = f.get("fix") or ""
        if fx:
            fixes.append(fx[:100])
        if f.get("category") == "needs_info":
            supports = "partial" if supports != "no" else "partial"
        else:
            supports = "no"
    # if only needs_info, partial
    if rel and all(f.get("category") == "needs_info" for f in rel):
        supports = "partial"
    gap = "；".join(gaps)[:300]
    fix = fixes[0] if fixes else "按对应 finding 的修复建议修改设计或降级主张"
    return needed, supports, gap, fix


def _goal_levels_for(kind: str, text: str) -> list[str]:
    if kind == "mechanism" or re.search(r"机制|介导|主要通过|主要来源", text):
        return ["mechanism_causal"]
    if kind == "synergy":
        return ["treatment_effect"]
    if kind == "extrapolation":
        return ["generalizability"]
    return ["treatment_effect", "exploratory"]



def _is_scope_limitation(text: str) -> bool:
    """True if text is a research-scope / limitation statement, not an affirmative over-claim."""
    t = (text or "").strip()
    if not t:
        return False
    # Affirmative over-claim cues → not a scope note
    if re.search(r"(作为.{0,16}(主要|核心|技术).{0,10}依据|可直接用于|足以支撑|证明可以推广|即可外推)", t):
        return False
    return bool(
        re.search(
            r"(主要适用于|适用范围|结论限于|仅适用于|局限(于|性)?|"
            r"不能直接(外推|推广|作为)|尚不能|需要结合后续|不等同于|仅供参考|"
            r"关于长期.{0,20}(需要|有待|尚)|外推需|有待(进一步|后续))",
            t,
        )
    )


def _collect_scope_notes(design, full_text, source_file, media_type) -> list[dict]:
    notes: list[dict] = []
    seen: set[str] = set()
    for c in design.get("claims_structured") or []:
        if not isinstance(c, dict):
            continue
        ct = (c.get("text") or "").strip()
        if not ct or not _is_scope_limitation(ct):
            continue
        key = ct[:120]
        if key in seen:
            continue
        seen.add(key)
        notes.append({"text": ct, "locations": c.get("locations") or []})
    # Also scan full text for standalone limitation sentences if none from structured claims
    if not notes:
        for m in re.finditer(r"[^。\n]{0,20}(主要适用于|适用范围|结论限于|不能直接外推)[^。\n]{0,80}[。]?", full_text or ""):
            ct = m.group(0).strip()
            if _is_scope_limitation(ct):
                notes.append({
                    "text": ct,
                    "locations": [make_locator(source_file, ct[:200], media_type=media_type)],
                })
                break
    return notes


def _has_extrapolation_claim(design: dict[str, Any], full_text: str) -> bool:
    for c in design.get("claims_structured") or []:
        if not isinstance(c, dict) or c.get("kind") != "extrapolation":
            continue
        # Mis-tagged scope limitations are NOT affirmative extrapolation claims
        if _is_scope_limitation(c.get("text") or ""):
            continue
        return True
    return bool(
        re.search(
            r"工程应用的主要|长期防污|连续运行.{0,12}(依据|单元)|为.{0,20}提供材料依据|主要技术依据",
            full_text,
        )
    )


def _extrapolation_claim_text(design: dict[str, Any], full_text: str) -> str:
    for c in design.get("claims_structured") or []:
        if not isinstance(c, dict) or c.get("kind") != "extrapolation" or not c.get("text"):
            continue
        if _is_scope_limitation(c["text"]):
            continue
        return c["text"]
    # Prefer affirmative over-claim snippets; skip pure limitation sentences
    for m in re.finditer(r"[^。\n]{0,40}(工程|连续运行|长期)[^。\n]{0,60}", full_text or ""):
        snip = m.group(0).strip()
        if _is_scope_limitation(snip):
            continue
        if re.search(r"(依据|支撑|证明|可直接|作为)", snip):
            return snip
    for m in re.finditer(
        r"[^。\n]{0,40}(工程应用的主要|主要技术依据|提供材料依据)[^。\n]{0,40}",
        full_text or "",
    ):
        snip = m.group(0).strip()
        if not _is_scope_limitation(snip):
            return snip
    return ""


def _parse_hypotheses_from_text(design, full_text, source_file, media_type):
    hyps = []
    for m in re.finditer(r"(H[1-9])\s*[：:]\s*([^\n。]+[。]?)", full_text):
        hyps.append({
            "id": m.group(1),
            "text": m.group(2).strip(),
            "expected_conclusion": m.group(2).strip(),
            "status": "stated",
            "locations": [make_locator(source_file, m.group(0)[:200], media_type=media_type)],
        })
    if hyps:
        return hyps
    for h in design.get("hypotheses") or []:
        if isinstance(h, str) and h.strip():
            mid = re.match(r"(H[1-9])", h)
            hyps.append({
                "id": mid.group(1) if mid else f"H{len(hyps)+1}",
                "text": h,
                "expected_conclusion": h,
                "status": "inferred",
                "locations": [fallback_locator(source_file, media_type)],
            })
    return hyps


def _snip(full_text, source_file, media_type, needle):
    idx = full_text.find(needle)
    if idx < 0:
        return []
    return [make_locator(source_file, full_text[max(0, idx - 20): idx + 60], media_type=media_type)]
