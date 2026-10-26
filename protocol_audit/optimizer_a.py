"""Design Optimizer Plan A — minimal necessary fixes (evidence-gap oriented, domain-agnostic)."""
from __future__ import annotations

from typing import Any
import re

GROUP_COLUMNS = [
    "group_name",
    "treatment",
    "control_role",
    "n_suggested",
    "replicate_unit",
    "notes",
]


def build_group_table(design: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for i, g in enumerate(design.get("groups") or [], start=1):
        role = _map_role(g.get("control_role_hint") or _infer_role(g))
        n = g.get("n_claimed") or _default_n(design)
        rows.append({
            "row_id": f"G{i:02d}",
            "group_name": g.get("name") or f"组{i}",
            "treatment": g.get("treatment") or "",
            "control_role": role,
            "n_suggested": str(n),
            "replicate_unit": _unit(design),
            "notes": g.get("quote") or "",
        })
    rows = [r for r in rows if not _looks_like_timepoint(r["group_name"])]
    if not rows:
        rows = [
            {
                "row_id": "G01",
                "group_name": "空白对照",
                "treatment": "无处理",
                "control_role": "blank",
                "n_suggested": _default_n(design),
                "replicate_unit": _unit(design),
                "notes": "由 Optimizer 占位；请在确认预览时补全",
            },
            {
                "row_id": "G02",
                "group_name": "处理组",
                "treatment": "目标处理",
                "control_role": "experimental",
                "n_suggested": _default_n(design),
                "replicate_unit": _unit(design),
                "notes": "由 Optimizer 占位；请在确认预览时补全",
            },
        ]
    return {"columns": list(GROUP_COLUMNS), "rows": rows, "notes": []}


def plan_a(
    design: dict[str, Any],
    findings: list[dict[str, Any]],
    group_table: dict[str, Any],
) -> dict[str, Any]:
    revised = {
        "columns": list(GROUP_COLUMNS),
        "rows": [dict(r) for r in group_table.get("rows") or []],
        "notes": [],
    }
    change_notes: list[dict[str, Any]] = []
    cid = 1
    roles = {r["control_role"] for r in revised["rows"]}
    units = design.get("units") or {}
    alloc = (units.get("allocation_unit") or "").strip()
    subsample = (units.get("subsample_unit") or "").strip()
    domain = _domain_context(design, findings)

    def add_note(
        summary: str,
        fids: list[str],
        burden: str = "low",
        *,
        solves: str = "",
        verification: str = "",
    ) -> None:
        nonlocal cid
        note = {
            "id": f"C{cid:02d}",
            "summary": summary,
            "addresses_finding_ids": fids,
            "burden": burden,
        }
        if solves:
            note["solves"] = solves
        if verification:
            note["verification"] = verification
        change_notes.append(note)
        cid += 1

    def fids_matching(*needles: str) -> list[str]:
        out = []
        for f in findings:
            blob = (f.get("title") or "") + (f.get("why_invalidates") or "") + (f.get("rule_id") or "")
            if any(n in blob for n in needles):
                out.append(f["id"])
        return out

    def fids_by_rule(*rule_ids: str) -> list[str]:
        return [f["id"] for f in findings if f.get("rule_id") in rule_ids]

    # --- Container / allocation-unit replication (ONLY when design/findings are about nested containers) ---
    container_fids = (
        fids_by_rule("structural_container_confound", "structural_pseudoreplication")
        or fids_matching("处理因素与实验容器", "伪重复：子样本", "水槽", "挂板被当作")
    )
    # Do NOT trigger on bare「混杂」— that catches buffer×pH etc.
    if container_fids and domain["has_nested_container"]:
        # Prefer parsed allocation_unit; else infer from findings/design blob (e.g. 水槽)
        unit_name = alloc or domain.get("inferred_alloc") or "容器"
        sub_name = subsample or domain.get("inferred_sub") or "子样本"
        for r in revised["rows"]:
            r["replicate_unit"] = f"{unit_name}层面的独立实验单位（{sub_name}不计独立 n）"
            r["n_suggested"] = f"每处理 ≥2–3 独立{unit_name}"
            r["notes"] = (r.get("notes") or "") + f"；Plan A：补{unit_name}层面重复或降级无法分离的因素主张"
        claim_bits = []
        if domain["mentions_uv"]:
            claim_bits.append("UV/联用交互")
        if domain["mentions_synergy"]:
            claim_bits.append("协同/交互")
        claim_bit = "、".join(claim_bits) if claim_bits else "无法在分配单位上分离的因素效应"
        add_note(
            f"在{unit_name}层面增加独立重复，或明确降级{claim_bit}主张；"
            f"不可仅更换统计模型掩盖{unit_name}层面独立重复缺失",
            container_fids[:3],
            "high",
            solves=f"{unit_name}与处理锁定或子样本当 n 导致效应不可分/伪重复",
            verification=f"每处理具备≥2 独立{unit_name}后，主效应/交互估计不再依赖单{unit_name}内子样本",
        )
        revised["notes"].append(f"{unit_name}层面独立重复是证据缺口核心；换 ANOVA/混合模型不能替代。")

    # --- Solvent / vehicle / adjuvant (domain-agnostic) ---
    solvent_fids = fids_by_rule("structural_solvent_confound") or fids_matching(
        "助溶剂", "载体对照", "助剂", "保护剂", "载体与", "vehicle", "与菌剂效应混杂", "与处理混杂且缺少匹配对照"
    )
    if solvent_fids and "solvent" not in roles:
        base = "匹配载体/助溶剂处理（无目标功能组分）"
        if domain["mentions_coating"]:
            base = "基础基质 + 匹配助溶剂（无功能组分）"
        revised["rows"].append({
            "row_id": f"G{len(revised['rows'])+1:02d}",
            "group_name": "助溶剂/载体对照",
            "treatment": base,
            "control_role": "solvent",
            "n_suggested": revised["rows"][0]["n_suggested"] if revised["rows"] else _default_n(design),
            "replicate_unit": revised["rows"][0]["replicate_unit"] if revised["rows"] else _unit(design),
            "notes": "Plan A：剥离功能组分效应与助溶剂/载体效应",
        })
        roles.add("solvent")
        add_note(
            "增加助溶剂/载体/助剂对照，使目标处理效应可分",
            solvent_fids[:3],
            "low",
            solves="目标处理与助剂/载体/保护剂效应混杂",
            verification="对照暴露与处理组匹配后，组间差异可归因于目标组分",
        )
    elif solvent_fids:
        add_note(
            "核对并补齐匹配的助剂/载体对照，使目标处理效应可分；或对称去除助剂后重做比较",
            solvent_fids[:3],
            "low",
            solves="目标处理与助剂/载体效应混杂",
            verification="有无目标组分的助剂暴露匹配，结论归因成立",
        )

    # --- Spatial / bench / position confounding (e.g. treatment locked to shelf/bench) ---
    spatial_fids = fids_by_rule("structural_position_confound") or fids_matching(
        "台面", "位置完全混杂", "位置混杂", "上层", "下层", "空间布局", "微气候",
        "不调整位置", "按编号顺序", "温室台面", "灌水处理与",
    )
    # Avoid double-counting pure tank/container notes already handled
    spatial_fids = [fid for fid in spatial_fids if fid not in (container_fids or [])]
    if spatial_fids:
        add_note(
            "解耦处理与空间位置：随机化或区组化台面/层架位置，使目标处理在各微气候位置上交叉；"
            "否则不得宣称可分离的处理主效应",
            spatial_fids[:3],
            "high",
            solves="处理因素与空间位置/微气候完全混杂",
            verification="位置与处理正交或区组后，处理效应估计不再依赖固定台面层",
        )

    # --- Blank only if finding says missing AND no reference ---
    blank_fids = [
        f for f in findings
        if f.get("dimension") == "controls" and "空白" in (f.get("title") or "") and f.get("category") == "confirmed"
    ]
    has_ref_row = any(
        r["control_role"] in ("blank", "reference", "negative")
        or re.search(r"B0|裸|空白|参照|基础涂层|无材料", r["group_name"] + r["treatment"])
        for r in revised["rows"]
    )
    if blank_fids and not has_ref_row and "blank" not in roles:
        revised["rows"].insert(0, {
            "row_id": f"G{len(revised['rows'])+1:02d}",
            "group_name": "空白对照",
            "treatment": "无处理 / 背景对照",
            "control_role": "blank",
            "n_suggested": _default_n(design),
            "replicate_unit": _unit(design),
            "notes": "Plan A：补空白对照",
        })
        add_note("增加空白对照，与处理组平行操作", [blank_fids[0]["id"]], "low")

    # --- Factor lock / buffer×pH style ---
    lock_fids = fids_by_rule("structural_factor_lock") or fids_matching(
        "锁定混杂", "缓冲剂", "缓冲体系", "因素完全锁定", "无法单独评价"
    )
    if lock_fids:
        add_note(
            "解耦锁定因素：在目标因子各水平使用同一调节方式，或做正交对照以分离伴随因子；"
            "否则降级无法分离的主效应主张",
            lock_fids[:2],
            "medium",
        )

    # --- Cocktail / mixed exposure attribution ---
    cocktail_fids = fids_by_rule("structural_cocktail_attribution") or fids_matching(
        "全量混合", "鸡尾酒", "同时加入", "无法单独归因", "混合投加"
    )
    if cocktail_fids:
        add_note(
            "将混合暴露改为单因子（及必要组合）设计，使声称的主导组分效应可估计；"
            "不可在鸡尾酒设计上归因单一组分",
            cocktail_fids[:1],
            "medium",
        )

    # --- Kinetics / volume or mass uncorrected ---
    vol_fids = fids_by_rule("structural_uncorrected_depletion") or fids_matching(
        "体积损耗", "未校正", "不补液", "不补加", "固定的初始体积"
    )
    if vol_fids:
        add_note(
            "校正重复取样造成的体积/质量变化（按剩余体积或累计取样质量衡算），"
            "或改为各时间点独立反应管/破坏性取样",
            vol_fids[:1],
            "medium",
        )

    # --- Regeneration mass balance ---
    regen_fids = fids_by_rule("structural_regen_mass_balance") or fids_matching(
        "再生", "循环", "中间轮", "质量", "投加量衰减"
    )
    # Avoid stealing mechanism-only「质量」— require regen context
    regen_fids = [
        fid for fid in regen_fids
        if any(
            any(k in ((f.get("title") or "") + (f.get("why_invalidates") or "")) for k in ("再生", "循环", "轮次", "解吸"))
            for f in findings if f["id"] == fid
        )
    ]
    if regen_fids:
        add_note(
            "再生/循环各轮称量（或衡算）固体质量并校正投加量，避免把机械流失记成再生失效",
            regen_fids[:1],
            "low",
        )

    # --- Process blank for modification workflow ---
    proc_fids = fids_by_rule("structural_process_blank") or fids_matching(
        "工艺空白", "工艺步骤", "浸渍", "热处理", "改性流程"
    )
    if proc_fids:
        add_note(
            "为改性/处理流程增加工艺空白（同步骤但不加功能组分，或匹配热处理/浸渍），"
            "使功能组分效应与工艺效应可分",
            proc_fids[:1],
            "medium",
        )

    # --- Factorial interaction ---
    fact_fids = fids_by_rule("structural_factorial_interaction") or fids_matching("协同", "交互", "析因")
    if fact_fids:
        add_note(
            "按析因结构预定义并报告交互效应（声明加性/乘性尺度）；"
            "停止用「联用组优于两单因素」或 one-way+事后比较作为协同判据",
            fact_fids[:1],
            "none",
        )

    # --- Destructive repeated measures ---
    dest_fids = fids_by_rule("structural_destructive_rm") or fids_matching("破坏性", "放回", "重复测量与破坏")
    if dest_fids:
        add_note(
            "停止破坏性测定后放回：改为各时间点独立牺牲样品，或仅终点做破坏性测定",
            dest_fids[:1],
            "medium",
        )

    # --- Claim downgrade: mechanism / extrapolation ---
    claim_fids = fids_by_rule("structural_corr_not_cause", "structural_over_extrapolation") or fids_matching(
        "机制", "相关不足以", "外推", "工程依据", "主导机制", "特异性"
    )
    if claim_fids:
        add_note(
            "收紧主张：相关/表征共变≠主要机制；短周期或简化工况结果不作为长期/工程主要依据",
            claim_fids[:3],
            "none",
        )
        revised["notes"].append("Plan A 优先修改主张边界，不机械堆叠新实验组。")

    # --- Generic pseudo if not already covered by container note ---
    if not container_fids:
        pseudo = [f for f in findings if f.get("dimension") == "pseudoreplication"]
        if pseudo:
            unit_name = alloc or "独立实验单位"
            for r in revised["rows"]:
                r["replicate_unit"] = f"{unit_name}（技术复孔另计）"
                if "独立" not in str(r["n_suggested"]):
                    r["n_suggested"] = f"≥3 独立{unit_name}（技术复孔不计入 n）"
            add_note(
                f"显式定义实验单位（当前解析：{unit_name}）；统计仅对独立重复推断",
                [pseudo[0]["id"]],
                "low",
            )

    if not change_notes:
        add_note("当前设计在规则层未发现必须修改的硬伤；保持原分组，仅建议完善报告措辞", [], "none")

    # --- P0: every confirmed blocker must map to an action ---
    covered = set()
    for n in change_notes:
        for fid in n.get("addresses_finding_ids") or []:
            covered.add(fid)

    blockers = [
        f for f in findings
        if f.get("category") == "confirmed" and f.get("severity") == "blocker"
    ]
    uncovered_reasons: dict[str, str] = {}
    for f in blockers:
        fid = f.get("id")
        if not fid or fid in covered:
            continue
        # synthesize action from finding.fix / title — never silently skip
        action = (f.get("fix") or "").strip()
        if not action:
            action = f"针对「{f.get('title') or fid}」补充可执行设计修改或明确降级主张"
            uncovered_reasons[fid] = "finding 未提供 fix 字段；已生成占位动作，需人工确认可执行性"
        problem = (f.get("why_invalidates") or f.get("title") or "").strip()[:200]
        verification = (
            "修改后复审：该 blocker 对应的混杂/单位/终点问题不再阻断主要结论；"
            "或主张已显式降级且与证据匹配"
        )
        add_note(
            action[:400],
            [fid],
            "high" if f.get("estimated_burden") in (None, "unknown", "high") else str(f.get("estimated_burden") or "medium"),
            solves=problem or (f.get("title") or ""),
            verification=verification,
        )
        covered.add(fid)

    for i, r in enumerate(revised["rows"], start=1):
        r["row_id"] = f"G{i:02d}"
        if r["control_role"] == "reference":
            r["control_role"] = "negative"

    # rebuild covered after synthesis
    covered = set()
    note_by_fid: dict[str, str] = {}
    for n in change_notes:
        for fid in n.get("addresses_finding_ids") or []:
            covered.add(fid)
            note_by_fid.setdefault(fid, n["id"])

    blocker_action_map = []
    incomplete = False
    for f in blockers:
        fid = f.get("id")
        if not fid:
            continue
        note_id = note_by_fid.get(fid)
        note = next((n for n in change_notes if n["id"] == note_id), None) if note_id else None
        if note_id and note:
            blocker_action_map.append({
                "finding_id": fid,
                "action": note.get("summary") or "",
                "problem": note.get("solves") or (f.get("why_invalidates") or f.get("title") or ""),
                "verification": note.get("verification") or "复审该 blocker 是否仍阻断主要结论",
                "change_note_id": note_id,
                "covered": True,
                "uncovered_reason": uncovered_reasons.get(fid),
            })
            if fid in uncovered_reasons:
                incomplete = True
        else:
            incomplete = True
            reason = "Plan A 无法生成对应动作；不得宣称 Plan A 完整"
            blocker_action_map.append({
                "finding_id": fid,
                "action": "",
                "problem": f.get("why_invalidates") or f.get("title") or "",
                "verification": "",
                "change_note_id": None,
                "covered": False,
                "uncovered_reason": reason,
            })

    completeness_note = (
        "全部 confirmed blocker 已建立 finding→action 映射。"
        if not incomplete
        else (
            "optimizer_incomplete：存在未充分覆盖的 confirmed blocker 或仅有占位动作——"
            + "；".join(
                f"{m['finding_id']}:{m.get('uncovered_reason')}"
                for m in blocker_action_map
                if m.get("uncovered_reason")
            )
        )
    )

    return {
        "plan_id": "A",
        "title": "最小必要修改",
        "rationale": (
            "只修改会直接影响主要结论可靠性的关键证据缺口"
            "（分配单位重复、对照可分性、因素解耦、空间位置、取样衡算、主张边界等），"
            "最大程度保留原方案；表述跟随本方案的分配单位与 findings，"
            "不套用无关领域模具；不以换模型替代设计重复。"
            "每个 confirmed blocker 必须有对应动作，否则标记 optimizer_incomplete。"
        ),
        "revised_group_table": revised,
        "change_notes": change_notes,
        "blocker_action_map": blocker_action_map,
        "optimizer_incomplete": incomplete,
        "completeness_note": completeness_note,
    }


def _domain_context(design: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, bool]:
    units = design.get("units") or {}
    blob = " ".join(
        [
            str(units.get("allocation_unit") or ""),
            str(units.get("subsample_unit") or ""),
            str(units.get("nesting") or ""),
            " ".join(f"{g.get('name','')} {g.get('treatment','')}" for g in design.get("groups") or []),
            " ".join(
                f"{(f.get('title') or '')} {(f.get('why_invalidates') or '')} {(f.get('fix') or '')}"
                for f in findings
            ),
        ]
    )
    alloc = (units.get("allocation_unit") or "")
    sub = (units.get("subsample_unit") or "")
    nested = bool(alloc and sub and alloc != sub) or bool(re.search(r"水槽|反应器|挂板", blob))
    # Nested container problem only if findings/units actually talk containers OR classic tank/coupon
    has_nested_container = bool(
        re.search(r"水槽|挂板|反应器|container|tank|实验容器|伪重复：子样本", blob, re.I)
        or any(
            (f.get("rule_id") or "") in ("structural_container_confound", "structural_pseudoreplication")
            for f in findings
        )
        or any(
            any(k in (f.get("title") or "") for k in ("实验容器", "伪重复：子样本", "水槽", "挂板"))
            for f in findings
        )
    )
    # If findings clearly describe tank/coupon nesting, treat as nested even when units parse missing
    if has_nested_container and not nested and re.search(r"水槽|挂板|实验容器|伪重复：子样本", blob):
        nested = True
    inferred_alloc = None
    inferred_sub = None
    if re.search(r"水槽", blob):
        inferred_alloc = "水槽"
    elif re.search(r"反应器", blob):
        inferred_alloc = "反应器"
    if re.search(r"挂板", blob):
        inferred_sub = "挂板"
    return {
        "has_nested_container": has_nested_container and nested,
        "mentions_uv": bool(re.search(r"UV|紫外", blob, re.I)),
        "mentions_synergy": bool(re.search(r"协同|交互|联用", blob)),
        "mentions_coating": bool(re.search(r"涂层|挂板|基材", blob)),
        "inferred_alloc": inferred_alloc,
        "inferred_sub": inferred_sub,
    }


def _looks_like_timepoint(name: str) -> bool:
    return bool(re.match(r"^D\d+$", (name or "").strip().upper())) or (name or "") in (
        "方案版本", "研究方向", "拟定日期", "计划周期"
    )


def _map_role(role: str) -> str:
    r = (role or "").lower()
    if r in ("blank", "solvent", "positive", "negative", "experimental", "other"):
        return r
    if r in ("reference", "control", "baseline"):
        return "negative"
    if r in ("vehicle",):
        return "solvent"
    return "experimental"


def _infer_role(g: dict[str, Any]) -> str:
    name = (g.get("name") or "") + (g.get("treatment") or "") + (g.get("control_role_hint") or "")
    if any(k in name for k in ("空白", "blank", "未处理", "裸", "无材料")):
        return "blank"
    if any(k in name for k in ("溶剂", "solvent", "vehicle", "DMSO", "助溶剂")):
        return "solvent"
    if "阳性" in name or "positive" in name.lower():
        return "positive"
    if "参照" in name or "B0" in name or "基础涂层" in name:
        return "reference"
    if "阴性" in name or "negative" in name.lower():
        return "negative"
    return "experimental"


def _default_n(design: dict[str, Any]) -> str:
    rep = design.get("replication") or {}
    units = design.get("units") or {}
    if units.get("allocation_unit"):
        return f"按{units.get('allocation_unit')}独立重复计数"
    if rep.get("has_biological"):
        return "与原文一致的独立生物重复"
    if rep.get("ambiguous_parallel"):
        return "待确认：独立重复 vs 技术平行"
    return "≥3（单位待定义）"


def _unit(design: dict[str, Any]) -> str:
    units = design.get("units") or {}
    if units.get("allocation_unit"):
        return f"分配单位={units.get('allocation_unit')}；子样本={units.get('subsample_unit') or '待定'}"
    u = (design.get("experimental_unit") or "").strip()
    if u:
        return u[:120]
    rep = design.get("replication") or {}
    if rep.get("has_biological"):
        return "独立生物重复/独立实验批次"
    if rep.get("ambiguous_parallel"):
        return "待确认（可能为技术平行）"
    return "待定义"
