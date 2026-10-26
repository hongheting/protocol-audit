"""LLM structured design extraction. Never imports gold standards."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_client import (
    chat_completion,
    extract_json_object,
    is_length_truncated,
    looks_like_truncated_json,
    resolve_provider,
)
from .locators import make_locator
from .schema_validate import ROOT

DESIGN_EXTRACT_SCHEMA_PATH = ROOT / "design-extract.v0.2.schema.json"

# Reliability-only (V0.1.2.1): truncation expand retry. Does NOT change scientific prompts.
DEFAULT_EXTRACT_MAX_TOKENS = 8192
EXPAND_EXTRACT_MAX_TOKENS = 16384


class LLMParseError(RuntimeError):
    """Raised when real LLM design extract fails after truncation retry (no silent heuristic success)."""

    def __init__(self, message: str, *, llm_meta: dict | None = None):
        super().__init__(message)
        self.llm_meta = llm_meta or {}


SYSTEM_PROMPT = """你是实验方案结构化解析器（ProtocolAudit Design Extract）。
只根据用户提供的原文块提取信息，输出严格 JSON。

硬性规则：
1. 不得编造原文未写明的实验条件、数值、组名或对照。
2. 缺信息时用 status="unknown" 或列入 unknowns，不要猜测填满。
3. 每条关键字段尽量带 locations（paragraph_id 或 table_id + original_text 摘录）。
4. 必须区分表类型 table_kind：
   - treatment_group_table：处理/实验分组表
   - metadata_table：版本、日期、研究方向等元信息
   - sampling_schedule_table：时间点/采样计划
   - other / unknown
   禁止把元信息表或采样时间表当成处理组。
5. 识别：假设 H1/H2/H3…及各自预期结论；实验因素与水平；实验组与对照组；
   处理分配单位 / 独立实验单位 / 子样本 / 技术重复；嵌套关系；
   时间点、重复测量、破坏性测定；检测指标及其支持的科学主张。
6. research_goal_level 不要自动升为 mechanism_causal；若原文未声明目标层级，保持 unspecified。
7. 只输出一个 JSON 对象，不要 Markdown 解释。
"""

USER_TEMPLATE = """请从下列带定位 ID 的实验方案原文中提取结构化设计。

输出 JSON 字段（可增补，但必须含这些）：
{{
  "parse_status": "ok|partial|failed",
  "research_question": "...",
  "research_goal_level": "unspecified",
  "hypotheses": [{{"id":"H1","text":"...","expected_conclusion":"...","status":"stated","locations":[{{"paragraph_id":"p-7","original_text":"..."}}]}}],
  "factors": [{{"name":"...","levels":["..."],"status":"stated","locations":[]}}],
  "groups": [{{"name":"B1","treatment":"...","factor_levels":{{}},"container_id":"A|B|null","n_claimed":"3","role":"experimental|reference|blank|solvent|control","status":"stated","locations":[]}}],
  "controls": [{{"type":"blank|solvent|reference|negative|positive","label":"...","present":true,"status":"stated","locations":[]}}],
  "units": {{
    "allocation_unit": "处理施加的单位，如水槽/反应器",
    "independent_experimental_unit": "统计上应独立的单位",
    "subsample_unit": "子样本，如挂板",
    "technical_replicate_unit": "技术重复，如复孔",
    "nesting": "文字描述嵌套",
    "status": "stated|inferred|unknown",
    "locations": []
  }},
  "timepoints": {{
    "points": ["D0","D7"],
    "repeated_measures": true,
    "destructive_assay": true,
    "returned_after_assay": true,
    "status": "stated",
    "locations": []
  }},
  "endpoints": [{{"text":"...","supports_claims":["H1"],"status":"stated","locations":[]}}],
  "claims": [{{"id":"C1","text":"...","kind":"treatment_effect|synergy|mechanism|extrapolation","status":"stated","locations":[]}}],
  "tables": [{{"table_id":"t-1","table_kind":"metadata_table|treatment_group_table|sampling_schedule_table|other","caption":"...","locations":[]}}],
  "statistical_plan": "...",
  "unknowns": [],
  "notes": []
}}

【原文块】
{blocks_text}
"""


def _blocks_to_prompt(blocks: list[dict[str, Any]]) -> str:
    lines = []
    for b in blocks:
        pid = b.get("paragraph_id") or ""
        tid = b.get("table_id") or ""
        btype = b.get("block_type") or "text"
        text = (b.get("text") or "").strip()
        if not text:
            continue
        tag = f"[{btype} paragraph_id={pid} table_id={tid}]"
        lines.append(f"{tag}\n{text}")
    return "\n\n".join(lines)


def validate_design_extract(doc: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["jsonschema not installed"]
    schema = json.loads(DESIGN_EXTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def llm_extract_design(
    blocks: list[dict[str, Any]],
    *,
    source_file: str,
    media_type: str | None,
    provider: str | None = None,
    log_dir: Path | None = None,
    max_tokens: int = DEFAULT_EXTRACT_MAX_TOKENS,
    expand_max_tokens: int = EXPAND_EXTRACT_MAX_TOKENS,
    allow_heuristic_fallback: bool = False,
) -> dict[str, Any]:
    """Call LLM and return {design_extract, llm_meta, errors}.

    Reliability (V0.1.2.1):
    - Detect max_tokens / length truncation or obviously truncated JSON.
    - Retry **once** with expanded max_tokens.
    - On persistent failure: ok=False, hard_fail=True, design_extract=None.
      Does **not** pretend success. Soft heuristic fallback only when
      allow_heuristic_fallback=True (legacy/tests); real LLM mode must leave it False.
    """
    prov = resolve_provider(provider)
    meta: dict[str, Any] = {
        "provider": prov,
        "purpose": "design_extract",
        "ok": False,
        "schema_errors": [],
        "fallback": False,
        "hard_fail": False,
        "truncation_detected": False,
        "expanded_retry": False,
        "max_tokens_initial": max_tokens,
        "max_tokens_used": max_tokens,
        "attempts": [],
    }
    if prov == "off":
        meta["error"] = "LLM off"
        meta["fallback"] = bool(allow_heuristic_fallback)
        meta["hard_fail"] = not allow_heuristic_fallback
        return {"design_extract": None, "llm_meta": meta, "errors": [meta["error"]]}

    user = USER_TEMPLATE.format(blocks_text=_blocks_to_prompt(blocks)[:28000])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

    def _attempt(tok: int, *, is_expand: bool) -> dict[str, Any]:
        result = chat_completion(
            messages=messages,
            provider=prov,
            max_tokens=tok,
            temperature=0.1,
            purpose="design_extract" if not is_expand else "design_extract_expand_retry",
            log_dir=log_dir,
        )
        attempt = {
            "max_tokens": tok,
            "expanded": is_expand,
            "ok": result.get("ok"),
            "finish_reason": result.get("finish_reason"),
            "usage": result.get("usage"),
            "latency_ms": result.get("latency_ms"),
            "error": result.get("error"),
            "length_truncated": False,
            "json_truncated_looks": False,
            "json_ok": False,
        }
        if not result.get("ok"):
            meta["attempts"].append(attempt)
            return {"result": result, "extract": None, "parse_error": result.get("error") or "llm failed", "attempt": attempt}

        content = result.get("content") or ""
        length_hit = is_length_truncated(result, requested_max_tokens=tok)
        json_looks_cut = looks_like_truncated_json(content)
        attempt["length_truncated"] = length_hit
        attempt["json_truncated_looks"] = json_looks_cut

        extract = None
        parse_error = None
        try:
            extract = extract_json_object(content)
            attempt["json_ok"] = True
        except Exception as e:  # noqa: BLE001
            parse_error = f"JSON parse failed: {e}"
            attempt["json_ok"] = False
            attempt["error"] = parse_error

        truncated = bool(length_hit or json_looks_cut or parse_error)
        attempt["truncated"] = truncated
        meta["attempts"].append(attempt)
        return {
            "result": result,
            "extract": extract,
            "parse_error": parse_error,
            "truncated": truncated,
            "attempt": attempt,
        }

    first = _attempt(max_tokens, is_expand=False)
    meta["max_tokens_used"] = max_tokens
    chosen = first

    first_json_ok = bool(first["result"].get("ok") and first.get("extract") is not None and not first.get("parse_error"))
    # Expand once when: HTTP ok but truncated/JSON broken; OR length hit even if JSON somehow parsed
    need_retry = False
    if first["result"].get("ok") and (
        first.get("truncated")
        or first.get("parse_error")
        or first.get("extract") is None
        or first.get("attempt", {}).get("length_truncated")
    ):
        # If JSON already clean AND not length-truncated, skip retry
        if first_json_ok and not first.get("attempt", {}).get("length_truncated") and not first.get("attempt", {}).get("json_truncated_looks"):
            need_retry = False
        else:
            need_retry = True
            meta["truncation_detected"] = True

    if need_retry:
        expand_to = max(int(expand_max_tokens), int(max_tokens) + 1)
        meta["expanded_retry"] = True
        meta["max_tokens_used"] = expand_to
        second = _attempt(expand_to, is_expand=True)
        chosen = second

    result = chosen["result"]
    meta.update({
        "model": result.get("model"),
        "usage": result.get("usage"),
        "latency_ms": result.get("latency_ms"),
        "request_id": result.get("request_id"),
        "finish_reason": result.get("finish_reason"),
    })

    extract = chosen.get("extract")
    parse_error = chosen.get("parse_error")
    # Accept iff transport ok + valid JSON object. Length finish_reason alone is OK
    # only when JSON parsed; otherwise hard-fail after the single expand retry.
    json_ok = bool(result.get("ok") and extract is not None and not parse_error)
    still_bad = not json_ok

    if still_bad:
        err = parse_error or result.get("error") or "LLM design extract failed after truncation retry"
        if meta.get("truncation_detected"):
            err = (
                f"LLM design extract truncated/failed after one expand retry "
                f"(initial_max_tokens={max_tokens}, expanded_max_tokens={meta['max_tokens_used']}): {err}"
            )
        meta["ok"] = False
        meta["hard_fail"] = True
        meta["error"] = err
        # Real LLM mode: never mark fallback success. Soft path only if explicitly allowed.
        meta["fallback"] = bool(allow_heuristic_fallback)
        return {
            "design_extract": None,
            "llm_meta": meta,
            "errors": [err],
            "raw_content": (result.get("content") or "")[:2000],
        }

    extract = _normalize_extract(extract, source_file, media_type)
    errs = validate_design_extract(extract)
    meta["schema_errors"] = errs
    if errs and extract.get("parse_status") == "ok":
        extract["parse_status"] = "partial"
    meta["ok"] = True
    meta["hard_fail"] = False
    meta["fallback"] = False
    meta["error"] = None
    return {"design_extract": extract, "llm_meta": meta, "errors": errs}



def _normalize_extract(extract: dict[str, Any], source_file: str, media_type: str | None) -> dict[str, Any]:
    def norm_locs(locs: Any) -> list[dict[str, Any]]:
        out = []
        if not isinstance(locs, list):
            return out
        for loc in locs:
            if not isinstance(loc, dict):
                continue
            out.append(make_locator(
                source_file,
                loc.get("original_text") or loc.get("original_text_excerpt") or loc.get("quote") or "",
                media_type=media_type,
                paragraph_id=loc.get("paragraph_id"),
                table_id=loc.get("table_id"),
                page_number=loc.get("page_number"),
            ))
        return out

    for key in ("hypotheses", "factors", "groups", "controls", "endpoints", "claims", "tables"):
        for item in extract.get(key) or []:
            if isinstance(item, dict) and "locations" in item:
                item["locations"] = norm_locs(item.get("locations"))
    for key in ("units", "timepoints"):
        obj = extract.get(key)
        if isinstance(obj, dict) and "locations" in obj:
            obj["locations"] = norm_locs(obj.get("locations"))
    extract.setdefault("parse_status", "ok")
    extract.setdefault("research_goal_level", "unspecified")
    # Never allow model to invent mechanism_causal upgrade here
    if extract.get("research_goal_level") == "mechanism_causal" and not extract.get("research_goal_level_user_set"):
        extract["research_goal_level"] = "unspecified"
        extract.setdefault("notes", []).append("model_suggested_mechanism_causal_downgraded_to_unspecified")
    return extract


def merge_llm_into_design(heuristic: dict[str, Any], extract: dict[str, Any] | None) -> dict[str, Any]:
    """Merge LLM extract into existing design dict used by rules/report."""
    if not extract:
        return heuristic
    out = dict(heuristic)
    out["_llm_extract"] = extract
    out["research_question"] = extract.get("research_question") or out.get("research_question") or ""
    hyps = extract.get("hypotheses") or []
    if hyps:
        out["hypotheses"] = [
            (h.get("id") + "：" + (h.get("text") or "")).strip("：") if isinstance(h, dict) else str(h)
            for h in hyps
        ]
        out["hypotheses_structured"] = hyps
        meta = dict(out.get("field_meta") or {})
        meta["hypothesis_status"] = hyps[0].get("status") if isinstance(hyps[0], dict) else "stated"
        meta["hypothesis_locations"] = (hyps[0].get("locations") if isinstance(hyps[0], dict) else []) or meta.get("hypothesis_locations") or []
        out["field_meta"] = meta

    # Groups: only from treatment_group_table / stated groups — never from metadata/schedule tables
    tables = {t.get("table_id"): t.get("table_kind") for t in (extract.get("tables") or []) if isinstance(t, dict)}
    out["table_classifications"] = [
        {"table_id": t.get("table_id"), "table_kind": t.get("table_kind"), "caption": t.get("caption") or ""}
        for t in (extract.get("tables") or []) if isinstance(t, dict)
    ]
    groups = []
    for g in extract.get("groups") or []:
        if not isinstance(g, dict):
            continue
        # skip if model accidentally put schedule rows as groups
        name = (g.get("name") or "").strip()
        if not name or name.upper().startswith("D") and name[1:].replace("0", "").isdigit():
            # D0/D7 style — reject as group
            if name.upper() in ("D0", "D7", "D14", "D21") or (name.upper().startswith("D") and name[1:].isdigit()):
                continue
        if any(k in name for k in ("方案版本", "研究方向", "拟定日期", "计划周期")):
            continue
        groups.append({
            "name": name,
            "treatment": g.get("treatment") or "",
            "n_claimed": g.get("n_claimed"),
            "status": g.get("status") or "stated",
            "quote": g.get("treatment") or name,
            "locations": g.get("locations") or [],
            "control_role_hint": g.get("role") or "",
            "container_id": g.get("container_id"),
            "factor_levels": g.get("factor_levels") or {},
        })
    if groups:
        out["groups"] = groups

    # Controls
    controls = []
    for c in extract.get("controls") or []:
        if not isinstance(c, dict):
            continue
        controls.append({
            "type": c.get("type") or "other",
            "label": c.get("label") or "",
            "present": bool(c.get("present")),
            "excludes_alternative": c.get("excludes_alternative") or "",
            "status": c.get("status") or ("stated" if c.get("present") else "missing"),
            "quote": c.get("label") or "",
            "locations": c.get("locations") or [],
        })
    # Infer reference/blank from groups if controls thin
    roles = {(g.get("control_role_hint") or "").lower() for g in out.get("groups") or []}
    names_blob = " ".join(f"{g.get('name','')} {g.get('treatment','')}" for g in out.get("groups") or [])
    has_ref = any(r in roles for r in ("blank", "reference", "control", "negative")) or bool(
        __import__("re").search(r"\bB0\b|裸|基础涂层|参照|对照", names_blob)
    )
    if controls:
        # If LLM says blank missing but we have B0/B1 reference, mark blank/reference present
        if has_ref:
            for c in controls:
                if c.get("type") in ("blank", "reference", "negative") and not c.get("present"):
                    c["present"] = True
                    c["status"] = "inferred"
                    c["label"] = c.get("label") or "参照/基础对照（来自分组表）"
            if not any(c.get("type") in ("blank", "reference") and c.get("present") for c in controls):
                controls.append({
                    "type": "reference",
                    "label": "B0/B1 参照或基础对照",
                    "present": True,
                    "excludes_alternative": "提供无处理/基础涂层基线",
                    "status": "inferred",
                    "quote": names_blob[:120],
                    "locations": [],
                })
        out["controls"] = controls
    elif has_ref:
        out["controls"] = [{
            "type": "reference",
            "label": "分组表中的参照/基础对照",
            "present": True,
            "excludes_alternative": "提供基线比较",
            "status": "inferred",
            "quote": names_blob[:120],
            "locations": [],
        }]

    units = extract.get("units") or {}
    if units:
        out["experimental_unit"] = units.get("independent_experimental_unit") or units.get("allocation_unit") or out.get("experimental_unit") or ""
        out["units"] = units
        rep = dict(out.get("replication") or {})
        nest = (units.get("nesting") or "") + " " + (units.get("subsample_unit") or "")
        alloc = units.get("allocation_unit") or ""
        indep = units.get("independent_experimental_unit") or ""
        # If allocation unit differs from claimed n unit, mark ambiguous
        if alloc and units.get("subsample_unit") and alloc != units.get("subsample_unit"):
            rep["ambiguous_parallel"] = True
            rep["status"] = "contradictory"
            rep["text"] = f"分配单位={alloc}; 子样本={units.get('subsample_unit')}; 声称为独立单位={indep}"
            rep["has_biological"] = False
            if units.get("locations"):
                rep["locations"] = units["locations"]
        if units.get("technical_replicate_unit"):
            rep["has_technical"] = True
        out["replication"] = rep

    tp = extract.get("timepoints") or {}
    if tp:
        out["timepoints"] = tp

    endpoints = extract.get("endpoints") or []
    if endpoints:
        out["outcomes"] = [
            {
                "text": e.get("text") or "",
                "status": e.get("status") or "stated",
                "locations": e.get("locations") or [],
                "supports_claims": e.get("supports_claims") or [],
            }
            for e in endpoints if isinstance(e, dict)
        ]

    if extract.get("statistical_plan"):
        out["statistical_plan"] = extract["statistical_plan"]
        out["statistics_status"] = "stated"

    claims = extract.get("claims") or []
    if claims:
        out["claims"] = [c.get("text") or "" for c in claims if isinstance(c, dict)]
        out["claims_structured"] = claims

    out["factors"] = extract.get("factors") or []
    # Goal level: keep unspecified unless user set; never auto mechanism
    if out.get("research_goal_level_source") != "user":
        rgl = extract.get("research_goal_level") or "unspecified"
        if rgl == "mechanism_causal":
            rgl = "unspecified"
        out["research_goal_level"] = rgl if rgl != "mechanism_causal" else "unspecified"
        if out.get("research_goal_level_source") not in ("user",):
            out["research_goal_level_source"] = out.get("research_goal_level_source") or "default"

    out["_tables_meta"] = tables
    return out
