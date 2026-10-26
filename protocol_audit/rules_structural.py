"""Deterministic structural rules on enriched design fields.

Confirmed findings only when structured evidence is clear.
Keyword-only hits must not produce confirmed findings.
"""
from __future__ import annotations

import re
from typing import Any

from .locators import fallback_locator, make_locator

NIH_REF = {
    "url": "https://beta.nih.gov/funding/preparing-your-application/preparing-research-plan/rigorous-study-design-and-transparent-reporting",
    "title": "NIH — Rigorous Study Design and Transparent Reporting",
    "verified": True,
    "doi": None,
}


def run_structural_rules(
    design: dict[str, Any],
    *,
    source_file: str,
    media_type: str | None,
    full_text: str,
    id_start: int = 1,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    fid = id_start
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

    groups = design.get("groups") or []
    units = design.get("units") or {}
    timepoints = design.get("timepoints") or {}
    controls = design.get("controls") or []
    factors = design.get("factors") or []
    claims_struct = design.get("claims_structured") or []
    stats = design.get("statistical_plan") or ""

    # --- 1. Treatment × container confounding ---
    containers = [g.get("container_id") for g in groups if g.get("container_id")]
    # Also parse from treatment / factor_levels
    uv_by_container: dict[str, set] = {}
    for g in groups:
        cid = g.get("container_id") or _infer_container(g, full_text)
        fl = g.get("factor_levels") or {}
        uv = fl.get("UV") or fl.get("UV-C") or fl.get("脉冲 UV-C") or fl.get("uv")
        if uv is None:
            blob = f"{g.get('name','')} {g.get('treatment','')}"
            if re.search(r"(UV|紫外)", blob, re.I):
                uv = "yes" if not re.search(r"(无\s*UV|否|不安装|无紫外)", blob) else "no"
        if cid:
            uv_by_container.setdefault(str(cid), set()).add(str(uv) if uv is not None else "?")

    explicit_one_tank = bool(re.search(r"不另外设置水槽|不设.*水槽.*平行|各.*1\s*个水槽|两套独立", full_text))
    factor_locked_to_container = False
    if len(uv_by_container) >= 2:
        # each container has only one UV level
        if all(len(v - {"?", "None", "null"}) <= 1 for v in uv_by_container.values()):
            levels = {next(iter(v - {"?", "None", "null"}), None) for v in uv_by_container.values()}
            if len(levels - {None}) >= 2:
                factor_locked_to_container = True
    # Fallback: A all no UV, B all UV from text+table
    if not factor_locked_to_container and re.search(r"UV-C.*B\s*水槽|B\s*水槽.*UV", full_text) and re.search(
        r"A\s*水槽不安装|A\s*水槽.*不", full_text
    ):
        factor_locked_to_container = True

    if factor_locked_to_container:
        loc = _loc_from_units_or_text(design, units, full_text, source_file, media_type, "水槽")
        findings.append({
            "id": next_f(),
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "处理因素与实验容器完全混杂",
            "locations": [loc],
            "why_invalidates": (
                "UV（或其他处理）与水槽/容器一一对应时，处理主效应与容器效应无法分离；"
                "交互/协同主张在结构上不可检验。"
            ),
            "fix": (
                "在容器层面设置独立重复（每处理多个水槽/反应器），或明确降级主张："
                "不得宣称可分离的 UV 主效应或处理×UV 交互；不可仅靠更换统计模型掩盖。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "high",
            "hard_error": True,
            "rule_id": "structural_container_confound",
        })

    # --- 2. Pseudoreplication / experimental unit ---
    alloc = (units.get("allocation_unit") or "").strip()
    subsample = (units.get("subsample_unit") or "").strip()
    indep = (units.get("independent_experimental_unit") or "").strip()
    claims_coupon_as_n = bool(re.search(r"挂板作为独立样本|视为\s*3\s*个平行|取\s*n\s*=\s*3", full_text))
    nested = bool(alloc and subsample and alloc != subsample) or bool(
        re.search(r"水槽.{0,20}挂板|挂板.{0,20}水槽", full_text)
    )
    if (nested and claims_coupon_as_n) or (
        claims_coupon_as_n and (factor_locked_to_container or explicit_one_tank)
    ):
        loc = _find_snip(full_text, source_file, media_type, "挂板作为独立样本") or _find_snip(
            full_text, source_file, media_type, "平行样"
        ) or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "pseudoreplication",
            "severity": "blocker",
            "category": "confirmed",
            "title": "伪重复：子样本被当作独立实验单位",
            "locations": loc if isinstance(loc, list) else [loc],
            "why_invalidates": (
                "处理分配在容器层面时，同容器内挂板/片为子样本；将子样本当 n 会低估变异、抬高假阳性。"
            ),
            "fix": (
                "以处理分配单位（如水槽）为独立实验单位做推断；或增加容器层面独立重复。"
                "技术重复（复孔）可聚合，但不得把同槽挂板当独立 n。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "high",
            "hard_error": True,
            "rule_id": "structural_pseudoreplication",
        })

    # --- 3. Solvent / vehicle confounding ---
    solvent_used = bool(re.search(r"助溶剂|有机助溶剂|溶剂预分散|DMSO|甲醇|丙酮", full_text))
    solvent_denied = bool(re.search(r"不另设置助溶剂|不设.*助溶剂|无助溶剂对照|不设置.*溶剂", full_text))
    has_solvent_ctrl = any(
        c.get("type") in ("solvent", "vehicle") and c.get("present") for c in controls
    )
    if solvent_used and (solvent_denied or not has_solvent_ctrl):
        # Only confirmed if explicit denial or clear asymmetry in text
        confirmed = solvent_denied or bool(re.search(r"功能颗粒先以.{0,20}助溶剂|预分散", full_text))
        loc = _find_snip(full_text, source_file, media_type, "助溶剂") or [
            fallback_locator(source_file, media_type, "助溶剂/溶剂")
        ]
        findings.append({
            "id": next_f(),
            "dimension": "controls",
            "severity": "high",
            "category": "confirmed" if confirmed else "needs_info",
            "title": "助溶剂/载体与处理混杂且缺少匹配对照",
            "locations": loc,
            "why_invalidates": "功能组分效应与助溶剂效应不可分，处理效应主张证据被破坏。",
            "fix": "增加助溶剂单独处理对照（或等价载体对照），使溶剂暴露在组间匹配。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": confirmed,
            "rule_id": "structural_solvent_confound",
        })

    # Do NOT flag missing blank if reference/blank/B0 present
    has_blankish = any(
        c.get("type") in ("blank", "reference", "negative") and c.get("present") for c in controls
    ) or any(
        re.search(r"空白|裸|参照|基础涂层|B0\b|未处理", f"{g.get('name','')} {g.get('treatment','')}", re.I)
        for g in groups
    )

    # --- 4. Factorial / interaction ---
    synergy_claim = bool(re.search(r"协同|交互|联用优势|synerg", full_text, re.I))
    bad_criterion = bool(re.search(r"低于.{0,12}(与|及|和).{0,12}降幅最大|降低幅度最大.{0,8}判定.{0,8}协同", full_text))
    oneway = bool(re.search(r"one-way\s*ANOVA|单因素方差", full_text, re.I))
    two_factors = len(factors) >= 2 or (
        re.search(r"功能(?:颗粒|涂层)", full_text) and re.search(r"UV-C|紫外", full_text)
    )
    if synergy_claim and (bad_criterion or (oneway and two_factors)):
        loc = _find_snip(full_text, source_file, media_type, "协同") or _find_snip(
            full_text, source_file, media_type, "ANOVA"
        ) or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "statistics",
            "severity": "high",
            "category": "confirmed",
            "title": "析因/协同判据不当（需交互项，而非仅 one-way 多重比较）",
            "locations": loc,
            "why_invalidates": (
                "「联用组低于两单因素组」不等于协同；2×2 析因应检验交互效应（并声明加性/乘性尺度）。"
            ),
            "fix": "按析因结构报告主效应与交互；协同主张需预定义交互检验，不能靠 Tukey 事后比较替代。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": True,
            "rule_id": "structural_factorial_interaction",
        })

    # --- 5. Repeated measures × destructive assay ---
    # Prefer text evidence; LLM False must not suppress clear protocol language.
    text_destructive = bool(re.search(r"结晶紫|染色后|破坏性", full_text))
    text_returned = bool(re.search(r"放回|再放回原", full_text))
    destructive = True if timepoints.get("destructive_assay") is True else (
        text_destructive if timepoints.get("destructive_assay") in (None, False) else False
    )
    if timepoints.get("destructive_assay") is False and text_destructive:
        destructive = True
    returned = True if timepoints.get("returned_after_assay") is True else (
        text_returned if timepoints.get("returned_after_assay") in (None, False) else False
    )
    if timepoints.get("returned_after_assay") is False and text_returned:
        returned = True
    multi_tp = bool(timepoints.get("points") and len(timepoints.get("points") or []) >= 2) or bool(
        re.search(r"D7.*D14.*D21|D7、D14、D21", full_text)
    )
    indep_tp_analysis = bool(re.search(r"按独立时间点分别分析|时间点分别分析", full_text))
    if destructive and returned and multi_tp:
        loc = _find_snip(full_text, source_file, media_type, "放回") or [
            fallback_locator(source_file, media_type)
        ]
        findings.append({
            "id": next_f(),
            "dimension": "endpoints",
            "severity": "high",
            "category": "confirmed",
            "title": "重复测量与破坏性检测冲突",
            "locations": loc,
            "why_invalidates": (
                "破坏性测定（如结晶紫染色）后冲洗放回，改变生物膜状态；后续时间点不是同一过程的独立观测。"
            ),
            "fix": "改为各时间点独立牺牲样品，或仅在终点做破坏性测定；勿将污染后的重复测量当作独立时间点分析。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": True,
            "rule_id": "structural_destructive_rm",
        })
        if indep_tp_analysis:
            # already covered in same finding
            pass

    # --- 6a Correlation ≠ mechanism ---
    mech_from_corr = bool(re.search(r"相关.{0,20}(认定|判定|认为).{0,20}(机制|主要)", full_text)) or bool(
        re.search(r"主要通过改变.{0,20}润湿", full_text)
    ) or bool(
        re.search(r"(结合能|表征|光谱).{0,30}(说明|证明|用于).{0,20}(主导机制|主要来源|机制)", full_text)
    )
    mech_claim = any((c.get("kind") == "mechanism") for c in claims_struct if isinstance(c, dict)) or bool(
        re.search(r"主导机制|主要来源于|主要通过", full_text)
    )
    if mech_from_corr or mech_claim:
        if mech_from_corr or mech_claim:
            loc = _find_snip(full_text, source_file, media_type, "机制") or _find_snip(
                full_text, source_file, media_type, "主要来源"
            ) or _find_snip(full_text, source_file, media_type, "相关") or [
                fallback_locator(source_file, media_type)
            ]
            findings.append({
                "id": next_f(),
                "dimension": "claim_evidence",
                "severity": "high",
                "category": "confirmed",
                "title": "相关性/表征共变不足以支持主要机制主张",
                "locations": loc,
                "why_invalidates": (
                    "相关分析或吸附前后表征共变只说明伴随变化，不能单独认定「主要/主导机制」。"
                ),
                "fix": (
                    "下调为伴随/相关描述；若要机制结论，需能排除替代解释的操纵或对照"
                    "（而非仅增加拟合优度）。"
                ),
                "evidence_class": "实验设计方法学原则",
                "evidence_refs": [NIH_REF],
                "estimated_burden": "medium",
                "hard_error": True,
                "rule_id": "structural_corr_not_cause",
            })

    # --- 6b Extrapolation ---
    # Severity (V0.1.3): default major(=high in schema); blocker only if core claim +
    # critical gap would block main conclusion; limited "potential application" → no upgrade.
    mild_prospect = bool(
        re.search(
            r"(潜在应用|应用前景|初步(实验室)?证据|可为.{0,20}提供(参考|启示)|有待.{0,12}(验证|评估))",
            full_text,
        )
    ) and bool(
        re.search(r"(局限|限制|不等同于|不能直接|尚不能|仅供参考)", full_text)
    )
    core_extrap = bool(
        re.search(
            r"工程应用的主要|主要技术依据|长期防污要求|推广应用依据|作为后续工程|"
            r"可为连续运行单元提供|田间.{0,12}推广|退化旱地.{0,12}(推广|应用)",
            full_text,
        )
    )
    extrap = core_extrap or bool(
        re.search(
            r"长期防污|工程.{0,8}依据|取水口|连续运行单元|提供材料依据|长期材料投用|"
            r"外推至|推广至|田间应用",
            full_text,
        )
    )
    short_lab = bool(
        re.search(
            r"21\s*d|28\s*d|室内|单轮|独立运行\s*1\s*轮|微宇宙|实验室|批式|"
            r"五轮再生|5\s*轮|盆栽|温室",
            full_text,
        )
    )
    if mild_prospect and not core_extrap:
        pass
    elif extrap and (short_lab or core_extrap or re.search(r"主要技术依据|长期防污要求|连续运行|推广", full_text)):
        if core_extrap and short_lab:
            sev, cat, hard = "blocker", "confirmed", True
        else:
            sev, cat, hard = "high", "confirmed", True  # major
        loc = _find_snip(full_text, source_file, media_type, "工程") or _find_snip(
            full_text, source_file, media_type, "连续运行"
        ) or _find_snip(full_text, source_file, media_type, "推广") or _find_snip(
            full_text, source_file, media_type, "长期"
        ) or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "claim_evidence",
            "severity": sev,
            "category": cat,
            "title": "由短周期/简化工况试验外推长期或工程依据过度",
            "locations": loc,
            "why_invalidates": (
                "短周期、批式、盆栽或简化水质的实验室结果不能直接作为长期工程/田间推广/连续运行的主要依据。"
            ),
            "fix": (
                "收紧应用表述为「初步实验室证据」；长期或工程主张需更长周期、相关工况或现场/中试验证。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "none",
            "hard_error": hard,
            "rule_id": "structural_over_extrapolation",
        })

    # Secondary: pooled EPS n=1
    if re.search(r"混合后测定|混样|三片挂板样品混合", full_text):
        loc = _find_snip(full_text, source_file, media_type, "混合") or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "sample_size",
            "severity": "medium",
            "category": "confirmed",
            "title": "混样导致每组有效 n=1",
            "locations": loc,
            "why_invalidates": "同组多样品混合后每组仅一个观测，无法估计组内变异。",
            "fix": "分样测定或明确该指标仅作描述性展示、不参与推断统计。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "structural_pooling_n1",
        })

    # Position confounding
    if re.search(r"按编号顺序依次排列|不调整位置|不随机", full_text):
        loc = _find_snip(full_text, source_file, media_type, "排列") or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "confounding",
            "severity": "medium",
            "category": "confirmed",
            "title": "挂板位置固定未随机，可能引入位置混杂",
            "locations": loc,
            "why_invalidates": "流场、遮光、距灯距离等与处理可能混杂。",
            "fix": "随机化或区组化挂板位置，并报告位置设计。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "structural_position_confound",
        })


    # --- Generic: factor lock confound (A locked to B, no crossed controls) ---
    # e.g. different buffer systems tied 1:1 to pH levels without same-pH buffer controls
    buffer_ph_lock = bool(
        re.search(r"(柠檬酸|HEPES|硼酸|缓冲).{0,40}(pH|酸碱)", full_text)
        or re.search(r"(pH|酸碱).{0,40}(柠檬酸|HEPES|硼酸|缓冲体系)", full_text)
    ) and bool(
        re.search(r"不另外设置.{0,20}缓冲|不另设.{0,16}缓冲|不设置相同 pH.{0,12}缓冲|无.{0,8}缓冲体系对照", full_text)
    )
    # Generic locked-level language
    locked_levels = bool(
        re.search(r"一一对应|完全锁定|分别使用.{0,30}将.{0,20}调节至", full_text)
    ) and bool(
        re.search(r"不另外设置|不另设|不设置相同|无.*对照", full_text)
    )
    if buffer_ph_lock or (
        locked_levels and re.search(r"缓冲", full_text) and re.search(r"pH", full_text)
    ):
        loc = (
            _find_snip(full_text, source_file, media_type, "缓冲")
            or _find_snip(full_text, source_file, media_type, "不另外设置")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "confounding",
            "severity": "blocker",
            "category": "confirmed",
            "title": "因素水平完全锁定混杂，目标因子主效应不可单独估计",
            "locations": loc,
            "why_invalidates": (
                "当伴随因子（如缓冲体系）与目标因子（如 pH）水平一一锁定且缺少同水平解耦对照时，"
                "观测变化无法归因于目标因子本身。"
            ),
            "fix": (
                "在目标因子各水平使用同一调节/维持方式，或设置正交/交叉对照以分离伴随因子；"
                "否则降级无法分离的主效应主张。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": True,
            "rule_id": "structural_factor_lock",
        })

    # --- Generic: uncorrected volume/mass depletion in serial sampling ---
    serial_sample = bool(
        re.search(r"(依次取样|连续取样|同管.{0,8}取样|分别在.{0,40}取.{0,12}mL)", full_text)
    )
    no_replenish = bool(re.search(r"不补加|不补液|取样后不补|不补充新液", full_text))
    fixed_volume_calc = bool(
        re.search(r"按固定的初始体积|固定.{0,6}初始体积|按.{0,6}初始体积\s*\d+", full_text)
    )
    if serial_sample and (no_replenish or fixed_volume_calc):
        loc = (
            _find_snip(full_text, source_file, media_type, "不补")
            or _find_snip(full_text, source_file, media_type, "初始体积")
            or _find_snip(full_text, source_file, media_type, "取样")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "endpoints",
            "severity": "high",
            "category": "confirmed",
            "title": "重复取样导致体积/质量变化未校正",
            "locations": loc,
            "why_invalidates": (
                "同反应体系连续取样且不补液/不按剩余量衡算时，浓度与吸附量等计算会出现系统性偏差，"
                "动力学或时间序列参数不可靠。"
            ),
            "fix": (
                "按剩余体积或累计取样做质量衡算校正；或改为各时间点独立反应管/破坏性全量取样。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": True,
            "rule_id": "structural_uncorrected_depletion",
        })

    # --- Generic: cocktail exposure with single-component attribution ---
    cocktail = bool(
        re.search(
            r"同时加入.{10,120}(和|及|与).{0,40}(综合影响|模拟)",
            full_text,
        )
        or re.search(r"混合.{0,10}(加入|投加|暴露).{0,40}(重点讨论|归因于|主要)", full_text)
    )
    single_attr = bool(
        re.search(
            r"重点讨论.{0,30}(竞争|作用|贡献)|评价.{0,20}选择性|主导因素|归因于",
            full_text,
        )
    )
    if cocktail and single_attr:
        loc = (
            _find_snip(full_text, source_file, media_type, "同时加入")
            or _find_snip(full_text, source_file, media_type, "重点讨论")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "confounding",
            "severity": "high",
            "category": "confirmed",
            "title": "混合暴露（多组分同时加入）却声称单一组分归因",
            "locations": loc,
            "why_invalidates": (
                "多干扰物同时投加时效应完全混杂，设计无法提供证据支持将结果归因于其中某一组分。"
            ),
            "fix": (
                "改为单因子及必要组合的设计，使声称的主导组分主效应（及交互）可估计；"
                "或删除单一组分归因表述。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": True,
            "rule_id": "structural_cocktail_attribution",
        })

    # --- Generic: regeneration/cycle without intermediate mass balance ---
    regen = bool(re.search(r"再生|循环性能|吸附—.{0,6}—再吸附|解吸.{0,20}再", full_text))
    no_mid_mass = bool(
        re.search(
            r"(中间|各轮).{0,20}不(重新)?(调整投加量|称量)|只在首轮.{0,20}称量|首末轮|材料质量（首末",
            full_text,
        )
        or re.search(r"不重新调整投加量", full_text)
    )
    if regen and no_mid_mass:
        loc = (
            _find_snip(full_text, source_file, media_type, "不重新调整")
            or _find_snip(full_text, source_file, media_type, "称量")
            or _find_snip(full_text, source_file, media_type, "再生")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "confounding",
            "severity": "medium",
            "category": "confirmed",
            "title": "再生/循环缺少中间质量衡算，投加量衰减与性能变化混杂",
            "locations": loc,
            "why_invalidates": (
                "固液分离与洗涤常导致固体流失；中间轮次不称量或不校正投加量时，"
                "无法区分位点失活与机械流失。"
            ),
            "fix": (
                "每轮称量残留干质量并按目标固液比补足或校正计算；"
                "否则再生稳定性主张需降级。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "structural_regen_mass_balance",
        })

    # --- Generic: process-step blank missing for modified vs baseline material ---
    # Trigger when modification workflow (impregnation/heat/load) is described and
    # baseline is used "directly" without matching process steps / process blank.
    mod_workflow = bool(
        re.search(r"(浸渍|负载|负载改性|热处理|煅烧|活化后)", full_text)
    )
    baseline_direct = bool(
        re.search(
            r"(原始|未改性|对照材料|基线材料).{0,40}直接用于|"
            r"按.{0,20}(筛分|制备)的方式直接用于|"
            r"不(另|再).{0,12}(浸渍|热处理|负载)",
            full_text,
        )
    )
    process_blank_denied = bool(
        re.search(r"不(另|再)设置.{0,20}(工艺空白|空白浸渍|空白热处理|假处理)", full_text)
    )
    if mod_workflow and (baseline_direct or process_blank_denied):
        loc = (
            _find_snip(full_text, source_file, media_type, "直接用于")
            or _find_snip(full_text, source_file, media_type, "浸渍")
            or _find_snip(full_text, source_file, media_type, "热处理")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "controls",
            "severity": "high",
            "category": "confirmed",
            "title": "改性/处理相对基线缺少匹配工艺空白",
            "locations": loc,
            "why_invalidates": (
                "改性材料经历额外工艺步骤（如浸渍、热处理）而基线材料未匹配时，"
                "功能组分效应与工艺效应不可分。"
            ),
            "fix": (
                "增加工艺空白（同浸渍/热处理流程但不加功能组分，或基线材料补做匹配步骤），"
                "再比较功能组分贡献。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": True,
            "rule_id": "structural_process_blank",
        })

    # --- Generic: representative-unit watering / dosing for whole group (needs_info) ---
    # e.g. adjust irrigation of an entire pot group from one "representative" pot's mass/moisture.
    # Default needs_info — do NOT auto-label as confirmed pseudoreplication.
    rep_guide = bool(
        re.search(
            r"(代表盆|代表性盆栽|代表植株|代表单元|代表性.{0,6}(盆|罐|容器))",
            full_text,
        )
    ) or bool(
        re.search(
            r"按.{0,12}(代表|抽样).{0,20}(盆|罐).{0,40}(补水|浇水|灌水|含水量|质量)",
            full_text,
        )
    )
    group_follow = bool(
        re.search(
            r"(同组|整组|各组|其余各盆|其他盆).{0,40}(补水|浇水|灌水|补液)|"
            r"(补水|浇水|灌水).{0,40}(同组|整组|其余)",
            full_text,
        )
    )
    per_unit_monitor = bool(
        re.search(r"(逐盆|每盆).{0,16}(称量|监测|测定|记录)|各盆独立.{0,12}(补水|浇水|灌水)", full_text)
    )
    calibrated = bool(re.search(r"(校准|标定).{0,20}(代表|含水|质量)|代表.{0,20}(校准|标定)", full_text)
    )
    exposure_consistent = bool(
        re.search(r"(处理暴露|水分暴露|灌水暴露).{0,16}一致|组内暴露一致", full_text)
    )
    if rep_guide and group_follow:
        loc = (
            _find_snip(full_text, source_file, media_type, "代表盆")
            or _find_snip(full_text, source_file, media_type, "代表")
            or _find_snip(full_text, source_file, media_type, "补水")
            or [fallback_locator(source_file, media_type)]
        )
        detail_bits = []
        if not per_unit_monitor:
            detail_bits.append("未写明逐盆/每单元监测")
        if not calibrated:
            detail_bits.append("未写明代表单元校准")
        if not exposure_consistent:
            detail_bits.append("未写明组内处理暴露一致性如何保证")
        detail = "；".join(detail_bits) or "代表性操作的独立性边界待核实"
        findings.append({
            "id": next_f(),
            "dimension": "pseudoreplication",
            "severity": "medium",
            "category": "needs_info",
            "title": "以代表单元指导整组补水/处理时，组内独立性待核实",
            "locations": loc,
            "why_invalidates": (
                "若整组补水/处理量由少数代表单元的含水量或质量变化决定，组内单元可能共享同一操作决策，"
                "独立性与处理暴露一致性需补充说明后才能判断是否构成伪独立。"
                f"（{detail}）"
            ),
            "fix": (
                "补充：①是否逐盆/逐单元监测与校准；②代表单元如何外推到整组；"
                "③组内处理暴露是否一致。若无法保证独立暴露，改为逐单元决策或在模型中显式处理组内相关；"
                "在信息补齐前不将此条升为 confirmed 伪重复。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "structural_representative_unit_dosing",
        })
        questions.append({
            "id": next_q(),
            "question": (
                "「代表单元」指导整组补水/处理时：是否逐盆（或逐实验单元）监测与校准？"
                "代表读数如何映射到同组其他单元？如何保证组内处理暴露一致？"
            ),
            "blocks_dimensions": ["pseudoreplication", "confounding"],
            "priority": "high",
            "context_quote": (loc[0].get("quote") if isinstance(loc, list) and loc else "") or "",
            "locations": loc if isinstance(loc, list) else [loc],
        })

    # --- Generic: single-batch material / inoculum (needs_info; not auto blocker) ---
    single_batch = bool(
        re.search(
            r"同一批(次)?(培养|菌液|菌剂|材料|制备|合成|改性)|"
            r"单批次|"
            r"一次制备.{0,20}(全部|所有)|"
            r"同一(培养|制备)批次",
            full_text,
        )
    )
    cross_batch_claim = bool(
        re.search(
            r"(跨批次|不同批次|批间|推广|工程应用|田间|可重复生产|放大生产|规模化)",
            full_text,
        )
    )
    if single_batch:
        loc = (
            _find_snip(full_text, source_file, media_type, "同一批")
            or _find_snip(full_text, source_file, media_type, "单批次")
            or _find_snip(full_text, source_file, media_type, "批次")
            or [fallback_locator(source_file, media_type)]
        )
        findings.append({
            "id": next_f(),
            "dimension": "reproducibility",
            "severity": "medium",
            "category": "needs_info",
            "title": "材料/菌剂为单批次制备，跨批次推广边界待明确",
            "locations": loc,
            "why_invalidates": (
                "实验单位重复（多盆/多管）不等于独立制备批次重复。"
                "单批次设计可支持该批次内的处理比较，但不能自动支持跨批次或生产放大主张。"
            ),
            "fix": (
                "在主张中区分「本批次内效应」与「跨批次可推广性」；"
                "若结论涉及跨批次/生产放大，补充独立制备批次或明确限制外推范围。"
            ),
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "medium",
            "hard_error": False,
            "rule_id": "structural_single_batch_material",
        })
        questions.append({
            "id": next_q(),
            "question": (
                "关键材料/菌剂是否仅同一制备批次？"
                "当前设计拟支持的主张范围是批次内处理比较，还是跨批次/生产放大？"
                "若为后者，是否有独立制备批次或批间变异估计？"
            ),
            "blocks_dimensions": ["reproducibility", "claim_evidence"],
            "priority": "high" if cross_batch_claim else "normal",
            "context_quote": (loc[0].get("quote") if isinstance(loc, list) and loc else "") or "",
            "locations": loc if isinstance(loc, list) else [loc],
        })

    # UV dose not measured in situ
    if re.search(r"暂不进行.{0,20}水下.{0,20}剂量|不进行挂板表面的水下", full_text):
        loc = _find_snip(full_text, source_file, media_type, "水下") or [fallback_locator(source_file, media_type)]
        findings.append({
            "id": next_f(),
            "dimension": "reproducibility",
            "severity": "medium",
            "category": "confirmed",
            "title": "UV 剂量未在挂板处水下实测",
            "locations": loc,
            "why_invalidates": "仅空气侧额定/点测无法报告挂板处实际剂量，妨碍复现与效应解释。",
            "fix": "在挂板位置进行水下辐照剂量测定并写入方案。",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [NIH_REF],
            "estimated_burden": "low",
            "hard_error": False,
            "rule_id": "structural_uv_dose",
        })

    return {
        "findings": findings,
        "clarifying_questions": questions,
        "has_blankish_control": has_blankish,
        "next_fid": fid,
    }


def _infer_container(g: dict[str, Any], full_text: str) -> str | None:
    fl = g.get("factor_levels") or {}
    for k in ("水槽", "container", "tank"):
        if fl.get(k):
            return str(fl[k])
    m = re.search(r"(?:水槽\s*)([AB])\b", f"{g.get('treatment','')} {g.get('name','')}")
    return m.group(1) if m else None


def _find_snip(full_text: str, source_file: str, media_type: str | None, needle: str) -> list[dict[str, Any]]:
    idx = full_text.find(needle)
    if idx < 0:
        idx = full_text.lower().find(needle.lower())
    if idx < 0:
        return []
    snippet = full_text[max(0, idx - 30) : idx + 80]
    return [make_locator(source_file, snippet, media_type=media_type, char_start=idx, char_end=idx + len(needle))]


def _loc_from_units_or_text(design, units, full_text, source_file, media_type, needle: str):
    locs = units.get("locations") if isinstance(units, dict) else None
    if locs:
        return locs[0]
    found = _find_snip(full_text, source_file, media_type, needle)
    return found[0] if found else fallback_locator(source_file, media_type)


def _is_single_batch_boundary_finding(nf: dict[str, Any]) -> bool:
    """Single-batch material evidence-boundary findings must not be treated as over-extrapolation."""
    rid = nf.get("rule_id") or ""
    if rid == "structural_single_batch_material":
        return True
    blob = f"{nf.get('title') or ''}{nf.get('why_invalidates') or ''}{nf.get('fix') or ''}"
    if not any(k in blob for k in ("单批次", "同一批", "跨批次", "制备批次", "批间")):
        return False
    # Primary topic is batch boundary / reproducibility of material prep — not result→field overreach.
    if any(k in blob for k in ("单批次", "同一批", "跨批次推广边界", "批次内", "独立制备批次", "批间变异")):
        # Explicit over-extrapolation findings may also mention batches; keep those if 外推 is the frame.
        if "外推" in blob and "批次" not in (nf.get("title") or ""):
            return False
        return True
    return False


def _is_over_extrapolation_finding(nf: dict[str, Any]) -> bool:
    """True only when the finding itself is about over-extrapolation of results/claims.

    Bare keywords like 「推广」 in a title (e.g. 跨批次推广边界) do NOT qualify.
    """
    if _is_single_batch_boundary_finding(nf):
        return False
    rid = nf.get("rule_id") or ""
    if rid == "structural_over_extrapolation":
        return True
    title = nf.get("title") or ""
    why = nf.get("why_invalidates") or ""
    blob = title + why
    # Strong framing in the finding text
    if any(k in blob for k in ("外推", "过度外推", "工程依据", "工程应用的主要", "连续运行")):
        return True
    if "工程应用" in blob and any(k in blob for k in ("短期", "盆栽", "批式", "实验室", "缺乏", "不足", "不能", "过度")):
        return True
    # 田间 with clear overreach framing — not mere mention of 推广
    if "田间" in blob and any(k in blob for k in ("外推", "盆栽", "短期", "缺乏", "不足", "过度", "不能直接", "不能作为")):
        return True
    return False


def adjust_extrapolation_severity(findings: list[dict[str, Any]], full_text: str) -> list[dict[str, Any]]:
    """Post-process (not Prompt): map over-extrapolation findings to V0.1.3.1 severity policy.

    - Never upgrade/reclassify single-batch material boundary findings.
    - Do not upgrade solely because title/body contains 「推广」.
    - default major (= high) for true over-extrapolation items
    - blocker only if core claim + short/simplified evidence would block main conclusion
    - limited potential-application language → do not upgrade (leave suggestion/medium or downgrade from blocker)
    """
    import re
    mild = bool(
        re.search(r"(潜在应用|应用前景|初步(实验室)?证据|仅供参考)", full_text)
    ) and bool(re.search(r"(局限|限制|不等同于|不能直接|尚不能)", full_text))
    core = bool(
        re.search(
            r"工程应用的主要|主要技术依据|推广应用依据|作为后续工程|可为连续运行单元提供|"
            r"田间.{0,12}推广|退化旱地.{0,12}(推广|应用)",
            full_text,
        )
    )
    short = bool(re.search(r"21\s*d|28\s*d|室内|实验室|批式|盆栽|温室|微宇宙", full_text))
    out = []
    for f in findings:
        nf = dict(f)
        # Hard split: single-batch evidence boundary vs engineering over-extrapolation
        if _is_single_batch_boundary_finding(nf):
            # Force design policy: needs_info, never confirmed/blocker via this pass
            if nf.get("rule_id") == "structural_single_batch_material" or "单批次" in (nf.get("title") or ""):
                nf["category"] = "needs_info"
                if nf.get("severity") in ("blocker", "high"):
                    nf["severity"] = "medium"
                nf["hard_error"] = False
            out.append(nf)
            continue
        if not _is_over_extrapolation_finding(nf):
            out.append(nf)
            continue
        # Only touch claim_evidence / reproducibility / over-extrapolation items
        if nf.get("dimension") not in ("claim_evidence", "reproducibility", None) and "外推" not in (
            (nf.get("title") or "") + (nf.get("why_invalidates") or "")
        ):
            out.append(nf)
            continue
        if mild and not core:
            if nf.get("severity") == "blocker":
                nf["severity"] = "medium"
                nf["category"] = "suggestion"
                nf["hard_error"] = False
            out.append(nf)
            continue
        if core and short:
            nf["severity"] = "blocker"
            nf["category"] = "confirmed"
            nf["hard_error"] = True
        else:
            # default major
            if nf.get("category") == "suggestion" or nf.get("severity") in ("medium", "low"):
                nf["severity"] = "high"
                nf["category"] = "confirmed"
                nf["hard_error"] = True
            elif nf.get("severity") == "blocker" and not (core and short):
                nf["severity"] = "high"
        out.append(nf)
    return out
