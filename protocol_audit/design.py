"""Heuristic extraction of experimental design from ingested blocks."""
from __future__ import annotations

import re
from typing import Any

from .locators import locator_from_block, make_locator

MECHANISM_PAT = re.compile(
    r"(通过.{0,12}介导|介导|mechanism|via\s+ROS|causal|因果关系|氧化应激促进|证明.{0,20}通过)",
    re.I,
)
EXPLORATORY_PAT = re.compile(r"(初步探索|exploratory|探索性|观察是否|描述性)", re.I)
TREATMENT_PAT = re.compile(r"(处理效应|treatment\s*effect|比较处理|组间差异|是否影响)", re.I)

SOLVENT_PAT = re.compile(r"(溶剂对照|solvent\s*control|vehicle\s*control|DMSO\s*对照)", re.I)
BLANK_PAT = re.compile(r"(空白对照|blank\s*control|未处理对照|negative\s*control|阴性对照)", re.I)
POSITIVE_PAT = re.compile(r"(阳性对照|positive\s*control)", re.I)

PARALLEL_PAT = re.compile(
    r"((?:每组|各组)?(?:设置|设)?\s*[三三3]?\s*(?:个)?(?:平行|重复|复孔|technical\s*replicate)[^\n。；;]{0,40})",
    re.I,
)
BIO_REP_PAT = re.compile(
    r"(独立(?:实验|生物)?(?:批次|重复)|biological\s*replicate|生物重复|独立反应器|独立培养)",
    re.I,
)
TECH_REP_PAT = re.compile(r"(技术重复|technical\s*replicate|复孔|同一批.{0,8}分成)", re.I)

ROS_PAT = re.compile(r"\bROS\b|活性氧|氧化应激", re.I)
GROUP_LINE_PAT = re.compile(
    r"(?:^|\n)\s*(?:组别|分组|Group)[^\n]{0,20}\n?",
    re.I,
)



def _is_negated(text: str, match_start: int, match_end: int) -> bool:
    """True if match is under local negation (未/不/无/缺少/没有…)."""
    window = text[max(0, match_start - 24) : match_end + 8]
    return bool(re.search(r"(未(?:另)?设|未区分|未说明|不设|不主张|不声称|不测定|缺少|没有|并非|不是|不宜|勿)", window))


def extract_design(
    blocks: list[dict[str, Any]],
    *,
    source_file: str,
    media_type: str | None,
    full_text: str,
    user_goal_level: str | None = None,
) -> dict[str, Any]:
    """Return extracted_design dict + helper hits for rules."""
    hits: dict[str, list[dict[str, Any]]] = {
        "mechanism": [],
        "parallel": [],
        "bio_rep": [],
        "tech_rep": [],
        "solvent": [],
        "blank": [],
        "ros": [],
        "groups": [],
    }

    for b in blocks:
        t = b.get("text") or ""
        loc = locator_from_block(b, source_file, media_type)
        for name, pat in (
            ("mechanism", MECHANISM_PAT),
            ("parallel", PARALLEL_PAT),
            ("bio_rep", BIO_REP_PAT),
            ("tech_rep", TECH_REP_PAT),
            ("solvent", SOLVENT_PAT),
            ("blank", BLANK_PAT),
            ("ros", ROS_PAT),
        ):
            for m in pat.finditer(t):
                if name in ("solvent", "blank", "bio_rep", "tech_rep", "parallel", "mechanism", "ros") and _is_negated(t, m.start(), m.end()):
                    continue
                # "平行数" alone in a header is weak; keep but bio/tech words inside 未区分 already skipped
                hits[name].append({"match": m.group(0), "block": b, "locator": loc})
                break

    # Goal level: never auto-upgrade to mechanism_causal
    goal = user_goal_level or "unspecified"
    goal_source = "user" if user_goal_level and user_goal_level != "unspecified" else (
        "user" if user_goal_level == "unspecified" else "default"
    )
    if not user_goal_level or user_goal_level == "unspecified":
        if EXPLORATORY_PAT.search(full_text):
            goal, goal_source = "exploratory", "inferred"
        elif TREATMENT_PAT.search(full_text) and not MECHANISM_PAT.search(full_text):
            goal, goal_source = "treatment_effect", "inferred"
        else:
            goal, goal_source = "unspecified", "default"
        # Explicit user unspecified stays if they passed it — but request default is unspecified
        if user_goal_level == "unspecified":
            goal, goal_source = "unspecified", "default"

    # Research question / hypothesis
    rq_text, rq_status, rq_locs = _first_sentence_about(
        blocks, source_file, media_type,
        keys=("科学问题", "研究目的", "目的", "research question", "hypothesis", "假设"),
    )
    hyp_parts = [h["match"] for h in hits["mechanism"][:2]]
    if not hyp_parts:
        hyp_text, hyp_status, hyp_locs = _first_sentence_about(
            blocks, source_file, media_type, keys=("假设", "hypothesis", "预期")
        )
    else:
        hyp_text = "；".join(hyp_parts)
        hyp_status = "stated"
        hyp_locs = [hits["mechanism"][0]["locator"]]

    groups = _extract_groups(blocks, source_file, media_type, full_text)
    controls = _extract_controls(hits, source_file, media_type)
    controls = mark_blank_from_groups(controls, groups)
    endpoints = _extract_endpoints(blocks, source_file, media_type, full_text)
    replication = _extract_replication(hits, full_text)
    claims = _extract_claims(hits, blocks, source_file, media_type)

    stats_text, stats_status, stats_locs = _first_sentence_about(
        blocks, source_file, media_type, keys=("统计", "t-test", "ANOVA", "显著性", "statistical")
    )

    unit_text, unit_status, unit_locs = _first_sentence_about(
        blocks, source_file, media_type, keys=("实验单位", "experimental unit", "独立样本")
    )
    if unit_status == "missing" and hits["bio_rep"]:
        unit_text = hits["bio_rep"][0]["match"]
        unit_status = "inferred"
        unit_locs = [hits["bio_rep"][0]["locator"]]

    design = {
        "research_question": rq_text,
        "hypotheses": [hyp_text] if hyp_text else [],
        "research_goal_level": goal,
        "research_goal_level_source": goal_source,
        "experimental_unit": unit_text or "",
        "groups": [
            {
                "name": g["name"],
                "treatment": g["treatment"],
                "n_claimed": g.get("n_claimed"),
                "status": g.get("status", "inferred"),
                "quote": g.get("quote"),
                "locations": g.get("locations", []),
            }
            for g in groups
        ],
        "controls": controls,
        "outcomes": [
            {"text": e["text"], "status": e["status"], "locations": e.get("locations", [])}
            for e in endpoints
        ],
        "replication": {
            "text": replication["text"],
            "status": replication["status"],
            "ambiguous_parallel": replication["ambiguous_parallel"],
            "has_biological": replication["has_biological"],
            "has_technical": replication["has_technical"],
            "locations": replication.get("locations", []),
        },
        "statistical_plan": stats_text or "",
        "statistics_status": stats_status,
        "statistics_locations": stats_locs,
        "claims": claims,
        "field_meta": {
            "research_question_status": rq_status,
            "research_question_locations": rq_locs,
            "hypothesis_status": hyp_status,
            "hypothesis_locations": hyp_locs,
            "experimental_unit_status": unit_status,
            "experimental_unit_locations": unit_locs,
        },
        "_hits": {k: [{"match": x["match"], "locator": x["locator"]} for x in v] for k, v in hits.items()},
    }
    return design


def apply_design_override(design: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    if not override:
        return design
    out = dict(design)
    for key in (
        "research_question",
        "hypotheses",
        "research_goal_level",
        "experimental_unit",
        "groups",
        "controls",
        "outcomes",
        "replication",
        "statistical_plan",
        "claims",
        "user_edits_summary",
    ):
        if key in override and override[key] is not None:
            out[key] = override[key]
    if "research_goal_level" in override and override["research_goal_level"]:
        out["research_goal_level_source"] = "user"
    return out


def _first_sentence_about(
    blocks: list[dict[str, Any]],
    source_file: str,
    media_type: str | None,
    keys: tuple[str, ...],
) -> tuple[str, str, list[dict[str, Any]]]:
    for b in blocks:
        t = b.get("text") or ""
        low = t.lower()
        if any(k.lower() in low for k in keys):
            # take first sentence or first 160 chars
            sent = re.split(r"[。\n]", t)
            pick = next((s.strip() for s in sent if any(k.lower() in s.lower() for k in keys)), t[:160])
            return pick[:300], "stated", [locator_from_block(b, source_file, media_type)]
    return "", "missing", []


def _extract_groups(
    blocks: list[dict[str, Any]],
    source_file: str,
    media_type: str | None,
    full_text: str,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    # From tables
    for b in blocks:
        if b.get("block_type") != "table":
            continue
        lines = [ln.strip() for ln in b["text"].splitlines() if ln.strip()]
        if not lines:
            continue
        header = lines[0].lower()
        if not any(k in header for k in ("组", "group", "处理", "treatment", "条件")):
            # still try if 2+ columns
            pass
        for ln in lines[1:]:
            if re.match(r"^[\|\s\-:]+$", ln):
                continue
            cells = [c.strip() for c in re.split(r"\s*\|\s*|\s{2,}", ln) if c.strip()]
            if len(cells) < 1:
                continue
            name = cells[0]
            treatment = cells[1] if len(cells) > 1 else cells[0]
            if name.lower() in ("组别", "group", "group_name", "名称"):
                continue
            groups.append({
                "name": name[:80],
                "treatment": treatment[:120],
                "n_claimed": cells[2] if len(cells) > 2 else None,
                "status": "stated",
                "quote": ln[:200],
                "locations": [locator_from_block(b, source_file, media_type)],
            })

    if groups:
        return groups

    # From prose patterns: 对照组 / 处理组
    prose_pats = [
        (r"(空白对照组?|空白组)", "空白对照", "blank"),
        (r"(溶剂对照组?|溶剂组|DMSO\s*组)", "溶剂对照", "solvent"),
        (r"(处理组|暴露组|加药组|[Xx]组|污染物组)", "处理", "experimental"),
        (r"(阳性对照组?)", "阳性对照", "positive"),
    ]
    for pat, default_name, role in prose_pats:
        for b in blocks:
            m = re.search(pat, b.get("text") or "")
            if m:
                groups.append({
                    "name": m.group(1),
                    "treatment": default_name,
                    "n_claimed": None,
                    "status": "stated",
                    "quote": m.group(0),
                    "locations": [locator_from_block(b, source_file, media_type)],
                    "control_role_hint": role,
                })
                break

    # Dedup by name
    seen = set()
    uniq = []
    for g in groups:
        if g["name"] in seen:
            continue
        seen.add(g["name"])
        uniq.append(g)
    return uniq


def _extract_controls(hits: dict[str, list], source_file: str, media_type: str | None) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    if hits["blank"]:
        h = hits["blank"][0]
        controls.append({
            "type": "blank",
            "label": h["match"],
            "present": True,
            "excludes_alternative": "排除基线/未处理背景效应",
            "status": "stated",
            "quote": h["match"],
            "locations": [h["locator"]],
        })
    else:
        controls.append({
            "type": "blank",
            "label": "空白对照",
            "present": False,
            "excludes_alternative": "排除基线/未处理背景效应",
            "status": "missing",
            "quote": "",
            "locations": [make_locator(source_file, "（方案中未明确写出空白对照）", media_type=media_type)],
        })

    if hits["solvent"]:
        h = hits["solvent"][0]
        controls.append({
            "type": "solvent",
            "label": h["match"],
            "present": True,
            "excludes_alternative": "排除溶剂本身对终点的影响",
            "status": "stated",
            "quote": h["match"],
            "locations": [h["locator"]],
        })
    else:
        # solvent often needed when DMSO/甲醇 mentioned
        controls.append({
            "type": "solvent",
            "label": "溶剂对照",
            "present": False,
            "excludes_alternative": "排除溶剂本身对终点的影响",
            "status": "missing",
            "quote": "",
            "locations": [make_locator(source_file, "（方案中未明确写出溶剂对照）", media_type=media_type)],
        })
    # Reconcile: prose/table groups that are untreated controls
    return controls


def mark_blank_from_groups(controls: list[dict[str, Any]], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """If a group looks like untreated control, mark blank present."""
    for g in groups:
        blob = f"{g.get('name','')} {g.get('treatment','')}"
        if re.search(r"(空白|blank|未处理)", blob, re.I) or (
            re.search(r"对照", blob) and re.search(r"(不加|无\s*X|无处理|不添加)", blob)
        ):
            for c in controls:
                if c.get("type") == "blank":
                    c["present"] = True
                    c["status"] = "stated"
                    c["label"] = g.get("name") or c.get("label")
                    c["quote"] = g.get("quote") or blob
                    if g.get("locations"):
                        c["locations"] = g["locations"]
            break
    return controls


def _extract_endpoints(
    blocks: list[dict[str, Any]],
    source_file: str,
    media_type: str | None,
    full_text: str,
) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    patterns = [
        (r"\bROS\b|活性氧", "ROS / 活性氧"),
        (r"\bATP\b", "ATP"),
        (r"转化频率|transformation\s*frequency|接合转移", "转化/转移频率"),
        (r"生长|OD600|生物量", "生长/生物量"),
        (r"基因表达|qPCR|RT-PCR", "基因表达"),
        (r"存活率|死亡率|viability", "存活率"),
    ]
    for pat, label in patterns:
        for b in blocks:
            if re.search(pat, b.get("text") or "", re.I):
                endpoints.append({
                    "text": label,
                    "status": "stated",
                    "locations": [locator_from_block(b, source_file, media_type)],
                })
                break
    return endpoints


def _extract_replication(hits: dict[str, list], full_text: str) -> dict[str, Any]:
    # If text says 未区分生物/技术重复, treat as ambiguous even if words appear
    explicitly_undistinguished = bool(re.search(r"未区分.{0,6}(生物|技术)?重复", full_text))
    has_bio = bool(hits["bio_rep"]) and not explicitly_undistinguished
    has_tech = bool(hits["tech_rep"])
    ambiguous = (bool(hits["parallel"]) and not has_bio) or explicitly_undistinguished
    text_parts = []
    locs = []
    for h in hits["parallel"][:1] + hits["bio_rep"][:1] + hits["tech_rep"][:1]:
        text_parts.append(h["match"])
        locs.append(h["locator"])
    status = "stated" if text_parts else "missing"
    if ambiguous:
        status = "contradictory"
    return {
        "text": "；".join(text_parts) if text_parts else "",
        "status": status,
        "ambiguous_parallel": ambiguous,
        "has_biological": has_bio,
        "has_technical": has_tech or bool(re.search(r"复孔|技术重复", full_text, re.I)),
        "locations": locs,
    }


def _extract_claims(
    hits: dict[str, list],
    blocks: list[dict[str, Any]],
    source_file: str,
    media_type: str | None,
) -> list[str]:
    claims: list[str] = []
    if hits["mechanism"]:
        claims.append(f"机制/介导主张：{hits['mechanism'][0]['match']}")
    if hits["ros"]:
        claims.append("污染物/处理引起 ROS 变化")
    # treatment effect
    for b in blocks:
        if re.search(r"(促进|抑制|影响).{0,20}(过程|频率|生长|表达)", b.get("text") or ""):
            claims.append("处理影响目标生物学过程")
            break
    return claims
