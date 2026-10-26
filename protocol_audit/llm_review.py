"""LLM scientific review pass — separate from deterministic rules; merge later."""
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
from .review_windows import build_review_windows, DEFAULT_WINDOW_CHARS

# Reliability-only (V0.1.3.3): review truncation expand retry. Does NOT change scientific prompts.
DEFAULT_REVIEW_MAX_TOKENS = 8192
EXPAND_REVIEW_MAX_TOKENS = 16384

SYSTEM = """你是实验设计科学审查员。根据结构化设计摘要与原文摘录，输出 JSON findings。
规则：
1. 每条 finding 必须带 quote 与 location（paragraph_id 或 table_id）；无原文依据则不要输出 confirmed。
2. 不得仅凭关键词定罪；必须说明为何使结论不成立。
3. category 只能是 confirmed | needs_info | suggestion。
4. 若存在 B0/裸基材/基础涂层参照，不得报「缺少空白对照」。
5. 96 孔复孔取均值是正确的技术重复处理，不得报成伪重复。
6. research_goal_level 不足时不要升为 mechanism_causal。
7. 只输出 JSON：{"findings":[...]}。
"""

USER_TMPL = """结构化设计摘要：
{design_summary}

原文（截断）：
{full_text}

请审查并输出 findings 数组，字段：
id(可选), dimension(confounding|pseudoreplication|controls|statistics|endpoints|claim_evidence|sample_size|reproducibility),
severity(blocker|high|medium|low), category, title, quote, paragraph_id, table_id,
why_invalidates, fix
重点检查：处理×容器混杂、伪重复、助溶剂混杂、析因交互、破坏性重复测量、相关≠机制、工程外推。
"""



class LLMReviewError(RuntimeError):
    """Raised when scientific review fails after truncation retry (optional hard path)."""

    def __init__(self, message: str, *, llm_meta: dict | None = None):
        super().__init__(message)
        self.llm_meta = llm_meta or {}


def _review_window_attempt(
    *,
    messages: list[dict[str, str]],
    prov: str,
    max_tokens: int,
    purpose: str,
    log_dir: Path | None,
    is_expand: bool,
) -> dict:
    """One chat call for a review window; detect length truncation / broken JSON."""
    result = chat_completion(
        messages=messages,
        provider=prov,
        max_tokens=max_tokens,
        temperature=0.1,
        purpose=purpose if not is_expand else f"{purpose}_expand_retry",
        log_dir=log_dir,
    )
    attempt = {
        "max_tokens": max_tokens,
        "expanded": is_expand,
        "ok": result.get("ok"),
        "finish_reason": result.get("finish_reason"),
        "usage": result.get("usage"),
        "latency_ms": result.get("latency_ms"),
        "error": result.get("error"),
        "length_truncated": False,
        "json_truncated_looks": False,
        "json_ok": False,
        "truncated": False,
        "findings_raw": [],
        "content_preview": (result.get("content") or "")[:240],
    }
    if not result.get("ok"):
        attempt["truncated"] = True
        return {"result": result, "findings": None, "parse_error": result.get("error") or "llm failed", "attempt": attempt}

    content = result.get("content") or ""
    length_hit = is_length_truncated(result, requested_max_tokens=max_tokens)
    json_looks_cut = looks_like_truncated_json(content)
    attempt["length_truncated"] = length_hit
    attempt["json_truncated_looks"] = json_looks_cut

    data = None
    parse_error = None
    try:
        data = extract_json_object(content)
        attempt["json_ok"] = True
    except Exception as e:  # noqa: BLE001
        parse_error = f"JSON parse failed: {e}"
        attempt["json_ok"] = False
        attempt["error"] = parse_error

    truncated = bool(length_hit or json_looks_cut or parse_error)
    # Even if JSON parses, length finish_reason means we may have lost findings → retry once
    if length_hit and attempt["json_ok"]:
        # Prefer expand when finish_reason=length; accept only if findings list present and non-truncated JSON
        findings_list = (data or {}).get("findings")
        if not isinstance(findings_list, list):
            truncated = True
            parse_error = parse_error or "length finish_reason without findings array"
            attempt["json_ok"] = False
    attempt["truncated"] = truncated
    findings = None
    if attempt["json_ok"] and isinstance(data, dict):
        findings = data.get("findings") or []
        if not isinstance(findings, list):
            findings = []
            attempt["json_ok"] = False
            attempt["truncated"] = True
            parse_error = "findings is not a list"
    return {
        "result": result,
        "findings": findings,
        "parse_error": parse_error,
        "truncated": truncated,
        "attempt": attempt,
    }


def llm_scientific_review(
    design: dict[str, Any],
    *,
    source_file: str,
    media_type: str | None,
    full_text: str,
    provider: str | None = None,
    log_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    max_windows: int = 3,
) -> dict[str, Any]:
    """Scientific review with methods-first windows + truncation expand-retry (tech V0.1.3.3).

    SYSTEM / USER_TMPL scientific Prompt text is unchanged; only the `full_text`
    slot content is prepared by review_windows. On finish_reason=length / truncated
    JSON: expand max_tokens once; still failing → partial/failed review, never
    silent empty findings pretending complete LLM review.
    """
    prov = resolve_provider(provider)
    meta: dict[str, Any] = {"provider": prov, "purpose": "scientific_review", "ok": False}
    windows, coverage = build_review_windows(
        full_text or "",
        window_chars=window_chars,
        max_windows=max_windows,
    )
    coverage_dict = coverage.to_dict()
    if artifacts_dir is not None:
        _write_review_artifacts(artifacts_dir, windows, coverage_dict, full_text or "")

    if prov == "off":
        meta["error"] = "LLM off"
        return {
            "findings": [],
            "llm_meta": meta,
            "review_coverage": coverage_dict,
            "review_windows": [w.meta() for w in windows],
        }

    summary = {
        "hypotheses": design.get("hypotheses_structured") or design.get("hypotheses"),
        "factors": design.get("factors"),
        "groups": [
            {k: g.get(k) for k in ("name", "treatment", "container_id", "n_claimed", "control_role_hint", "factor_levels")}
            for g in (design.get("groups") or [])
        ],
        "units": design.get("units"),
        "timepoints": design.get("timepoints"),
        "controls": design.get("controls"),
        "statistical_plan": design.get("statistical_plan"),
        "table_classifications": design.get("table_classifications"),
    }
    design_summary = json.dumps(summary, ensure_ascii=False)[:12000]

    if not windows:
        meta["error"] = "empty review windows"
        return {
            "findings": [],
            "llm_meta": meta,
            "review_coverage": coverage_dict,
            "review_windows": [],
        }

    all_findings: list[dict[str, Any]] = []
    window_metas: list[dict[str, Any]] = []
    any_ok = False
    any_partial = False
    last_error = None
    truncation_detected = False
    expanded_retry_any = False
    max_tokens_initial = DEFAULT_REVIEW_MAX_TOKENS
    max_tokens_used = DEFAULT_REVIEW_MAX_TOKENS

    for w in windows:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER_TMPL.format(
                design_summary=design_summary,
                full_text=w.text,
            )},
        ]
        purpose = "scientific_review" if w.priority == 0 else f"scientific_review_{w.window_id}"
        first = _review_window_attempt(
            messages=messages,
            prov=prov,
            max_tokens=DEFAULT_REVIEW_MAX_TOKENS,
            purpose=purpose,
            log_dir=log_dir,
            is_expand=False,
        )
        chosen = first
        need_retry = False
        first_ok_json = bool(
            first["result"].get("ok")
            and first.get("findings") is not None
            and not first.get("parse_error")
            and first.get("attempt", {}).get("json_ok")
        )
        if first["result"].get("ok") and (
            first.get("truncated")
            or first.get("parse_error")
            or first.get("findings") is None
            or first.get("attempt", {}).get("length_truncated")
            or first.get("attempt", {}).get("json_truncated_looks")
        ):
            if first_ok_json and not first.get("attempt", {}).get("length_truncated") and not first.get("attempt", {}).get("json_truncated_looks"):
                need_retry = False
            else:
                need_retry = True
                truncation_detected = True

        if need_retry:
            expanded_retry_any = True
            expand_to = EXPAND_REVIEW_MAX_TOKENS
            max_tokens_used = max(max_tokens_used, expand_to)
            second = _review_window_attempt(
                messages=messages,
                prov=prov,
                max_tokens=expand_to,
                purpose=purpose,
                log_dir=log_dir,
                is_expand=True,
            )
            # Beta reliability: never discard a usable first pass when expand is worse.
            def _usable(att: dict) -> bool:
                return bool(
                    att.get("result", {}).get("ok")
                    and att.get("findings") is not None
                    and not att.get("parse_error")
                    and att.get("attempt", {}).get("json_ok")
                )
            if _usable(second):
                chosen = second
            elif _usable(first):
                chosen = first
                # Keep truncation flag so boundary can still warn if first looked cut.
                if first.get("truncated") or first.get("attempt", {}).get("length_truncated"):
                    truncation_detected = True
            else:
                chosen = second

        result = chosen["result"]
        attempt = chosen.get("attempt") or {}
        wmeta = {
            "window_id": w.window_id,
            "ok": False,
            "model": result.get("model"),
            "usage": result.get("usage"),
            "latency_ms": result.get("latency_ms"),
            "request_id": result.get("request_id"),
            "error": chosen.get("parse_error") or result.get("error"),
            "start": w.start,
            "end": w.end,
            "reason": w.reason,
            "finish_reason": result.get("finish_reason") or attempt.get("finish_reason"),
            "max_tokens_initial": max_tokens_initial,
            "max_tokens_used": attempt.get("max_tokens") or max_tokens_initial,
            "truncation_detected": bool(attempt.get("length_truncated") or attempt.get("json_truncated_looks") or truncation_detected),
            "expanded_retry": bool(need_retry),
            "length_truncated": bool(attempt.get("length_truncated")),
            "json_ok": bool(attempt.get("json_ok")),
            "partial_review": False,
        }
        window_metas.append(wmeta)

        still_bad = not (
            result.get("ok")
            and chosen.get("findings") is not None
            and not chosen.get("parse_error")
            and attempt.get("json_ok")
        )
        # After expand, length alone is OK only if JSON+findings parsed cleanly
        if still_bad:
            err = (
                chosen.get("parse_error")
                or result.get("error")
                or "LLM scientific review failed after truncation retry"
            )
            if need_retry or attempt.get("length_truncated"):
                err = (
                    f"LLM scientific review truncated/failed after one expand retry "
                    f"(window={w.window_id}, initial_max_tokens={DEFAULT_REVIEW_MAX_TOKENS}, "
                    f"expanded_max_tokens={attempt.get('max_tokens')}): {err}"
                )
            wmeta["error"] = err
            wmeta["partial_review"] = True
            wmeta["ok"] = False
            any_partial = True
            last_error = err
            # Do NOT silently accept empty findings as a successful LLM review for this window
            continue

        any_ok = True
        wmeta["ok"] = True
        wmeta["error"] = None
        raw_findings = chosen.get("findings") or []
        normalized = _normalize_llm_findings(
            raw_findings,
            source_file=source_file,
            media_type=media_type,
            id_prefix=f"L{w.window_id}",
        )
        for nf in normalized:
            nf["review_window_id"] = w.window_id
            nf["review_window_range"] = {"start": w.start, "end": w.end}
            nf["origin"] = "llm_review"
        all_findings.extend(normalized)

    # Soft-merge across windows (keep duplicates annotated; never silent drop)
    merged = merge_findings([], all_findings) if all_findings else []

    # Review completeness: full LLM success only if every window succeeded
    all_windows_ok = bool(windows) and all(m.get("ok") for m in window_metas)
    partial_review = bool(any_partial) or (bool(windows) and not all_windows_ok)
    # Never claim full LLM review success when truncated/failed windows remain
    review_ok = bool(any_ok) and not partial_review
    if partial_review and any_ok:
        # Some windows produced findings; mark partial — do not pretend comprehensive LLM review
        status = "partial"
        err_msg = last_error or "one or more review windows failed/truncated after expand retry"
    elif review_ok:
        status = "complete"
        err_msg = None
    else:
        status = "failed"
        err_msg = last_error or "all review windows failed"

    meta.update({
        "ok": review_ok,
        "partial_review": partial_review,
        "review_status": status,
        "hard_fail": status == "failed",
        "truncation_detected": truncation_detected or any(m.get("truncation_detected") for m in window_metas),
        "expanded_retry": expanded_retry_any,
        "max_tokens_initial": max_tokens_initial,
        "max_tokens_used": max_tokens_used,
        "model": next((m.get("model") for m in window_metas if m.get("model")), None),
        "usage": _sum_usage([m.get("usage") for m in window_metas]),
        "latency_ms": sum((m.get("latency_ms") or 0) for m in window_metas),
        "request_id": None,
        "error": err_msg,
        "window_count": len(windows),
        "windows_ok": sum(1 for m in window_metas if m.get("ok")),
        "windows": window_metas,
        "review_coverage_summary": coverage.summary_zh(),
        "llm_findings_count": len(all_findings),
        # Explicit: empty findings with ok=False must not be read as "LLM found nothing wrong"
        "pretend_complete_llm_review": False,
    })
    return {
        "findings": merged,
        "llm_meta": meta,
        "review_coverage": coverage_dict,
        "review_windows": [w.meta() for w in windows],
        "partial_review": partial_review,
        "review_status": status,
    }


def _sum_usage(usages: list[Any]) -> dict[str, int]:
    out = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in usages:
        if not isinstance(u, dict):
            continue
        out["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        out["completion_tokens"] += int(u.get("completion_tokens") or 0)
        out["total_tokens"] += int(u.get("total_tokens") or (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0))
    return out


def _write_review_artifacts(
    artifacts_dir: Path,
    windows: list[Any],
    coverage_dict: dict[str, Any],
    full_text: str,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "full_text_extract.txt").write_text(full_text, encoding="utf-8")
    (artifacts_dir / "review_coverage.json").write_text(
        json.dumps(coverage_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for w in windows:
        (artifacts_dir / f"sent_{w.window_id}.txt").write_text(w.text, encoding="utf-8")
        (artifacts_dir / f"sent_{w.window_id}.meta.json").write_text(
            json.dumps(w.meta(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _normalize_llm_findings(
    raw_findings: list[Any],
    *,
    source_file: str,
    media_type: str | None,
    id_prefix: str = "LLM",
) -> list[dict[str, Any]]:
    normalized = []
    for i, f in enumerate(raw_findings, start=1):
        if not isinstance(f, dict):
            continue
        quote = f.get("quote") or f.get("original_text") or ""
        cat = f.get("category") or "needs_info"
        if cat == "confirmed" and len(quote.strip()) < 4:
            cat = "needs_info"
        title = (f.get("title") or "")[:120]
        if _is_forbidden_false_positive(title, quote):
            continue
        dim = f.get("dimension") or "confounding"
        if dim not in {
            "hypothesis", "claim_evidence", "controls", "confounding", "pseudoreplication",
            "sample_size", "endpoints", "statistics", "reproducibility",
        }:
            dim = "confounding"
        loc = make_locator(
            source_file,
            quote[:500],
            media_type=media_type,
            paragraph_id=f.get("paragraph_id"),
            table_id=f.get("table_id"),
        )
        normalized.append({
            "id": f"{id_prefix}{i:02d}",
            "dimension": dim,
            "severity": f.get("severity") if f.get("severity") in ("blocker", "high", "medium", "low") else "medium",
            "category": cat if cat in ("confirmed", "needs_info", "suggestion") else "needs_info",
            "title": title or "LLM 审查意见",
            "locations": [loc],
            "why_invalidates": f.get("why_invalidates") or "",
            "fix": f.get("fix") or "",
            "evidence_class": "实验设计方法学原则",
            "evidence_refs": [],
            "estimated_burden": "unknown",
            "hard_error": cat == "confirmed" and f.get("severity") in ("blocker", "high"),
            "rule_id": "llm_review",
            "source": "llm_review",
            "origin": "llm_review",
        })
    return normalized



def _is_forbidden_false_positive(title: str, quote: str) -> bool:
    blob = title + " " + quote
    if re_search_blank_missing(blob):
        return True
    if ("96" in blob or "复孔" in blob) and ("伪重复" in blob or "独立" in title):
        # flagging technical replicates as pseudo — reject
        return True
    return False


def re_search_blank_missing(blob: str) -> bool:
    import re
    return bool(re.search(r"缺少空白|缺少未处理对照|缺少空白/未处理|missing blank", blob, re.I))


def merge_findings(rule_findings: list[dict[str, Any]], llm_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge findings; keep suspected duplicates with relation annotations (do not drop).

    V0.1.3.1:
    - Never link solely because both titles contain 「混杂」.
    - Require shared root-cause / same design defect / substantial evidence overlap.
    - Uncertain → keep both with relation none (optional association note only when weak cue overlap).
    - true_duplicate / similar_different_mechanism still annotate; never silently delete.
    """
    merged: list[dict[str, Any]] = []
    for f in rule_findings:
        nf = dict(f)
        nf.setdefault("duplicate_relation", "none")
        merged.append(nf)

    THEME_TOKENS = (
        "混杂", "伪重复", "助溶剂", "助剂", "海藻糖", "协同", "交互", "破坏性", "机制",
        "外推", "混样", "位置", "台面", "剂量", "体积", "缓冲", "工艺", "水分",
    )

    def themes_of(title: str) -> set[str]:
        return {tok for tok in THEME_TOKENS if tok in (title or "")}

    SPECIFIC = {
        "伪重复", "助溶剂", "助剂", "海藻糖", "协同", "交互", "破坏性", "外推",
        "混样", "剂量", "体积", "缓冲", "工艺", "台面",
    }
    BROAD = {"混杂", "机制", "位置", "水分"}

    # Root-cause cue groups: findings in different groups are independent even if both say 混杂
    ROOT_CAUSE_GROUPS: tuple[tuple[str, ...], ...] = (
        ("台面", "长台", "层架", "空间位置", "微气候", "上层", "下层", "位置完全"),
        ("海藻糖", "保护剂", "助剂", "助溶剂", "载体对照", "接种液", "溶剂对照"),
        ("缓冲", "pH", "磷酸盐缓冲"),
        ("水槽", "容器", "tank"),
        ("体积", "损耗", "取样体积", "质量变化未校正"),
        ("破坏性", "石英砂", "牺牲", "拔除"),
        ("外推", "工程依据", "田间推广", "连续运行"),
        ("相关", "机制主张", "因果"),
        ("伪重复", "子样本", "挂板当"),
        ("工艺空白", "灭活", "改性空白"),
        ("单批次", "同一批", "跨批次"),
        ("代表盆", "代表单元", "整组补水"),
    )

    def _blob(f: dict) -> str:
        return f"{f.get('title') or ''}{f.get('why_invalidates') or ''}{f.get('fix') or ''}"

    def _root_groups(f: dict) -> set[int]:
        blob = _blob(f)
        hits: set[int] = set()
        for i, cues in enumerate(ROOT_CAUSE_GROUPS):
            if any(c in blob for c in cues):
                hits.add(i)
        return hits

    def _jaccard_chars(a: str, b: str) -> float:
        def grams(s: str) -> set[str]:
            s = s or ""
            return {s[i : i + 2] for i in range(max(0, len(s) - 1))} or {s}

        A, B = grams(a), grams(b)
        if not A or not B:
            return 0.0
        return len(A & B) / len(A | B)

    def _shared_root_or_evidence(a: dict, b: dict) -> bool:
        ga, gb = _root_groups(a), _root_groups(b)
        if ga and gb and (ga & gb):
            return True
        # Substantial textual evidence overlap (title+why)
        return _jaccard_chars(_blob(a), _blob(b)) >= 0.28

    def is_true_duplicate(a: dict, b: dict) -> bool:
        if a.get("dimension") != b.get("dimension"):
            return False
        ta, tb = themes_of(a.get("title") or ""), themes_of(b.get("title") or "")
        shared = ta & tb
        if not shared:
            # same rule_id can still be true dup
            if a.get("rule_id") and a.get("rule_id") == b.get("rule_id"):
                return _shared_root_or_evidence(a, b)
            return False
        # Shared 「混杂」 alone is NEVER enough
        if shared == {"混杂"} or shared <= {"混杂"}:
            return _shared_root_or_evidence(a, b) and _jaccard_chars(a.get("title") or "", b.get("title") or "") >= 0.35
        # Specific shared theme → require root/evidence overlap (avoid 助剂 vs unrelated)
        if shared & SPECIFIC:
            return _shared_root_or_evidence(a, b) or _jaccard_chars(a.get("title") or "", b.get("title") or "") >= 0.3
        # Broad-only: require root cause OR strong title overlap
        if shared <= BROAD:
            return _shared_root_or_evidence(a, b) and _jaccard_chars(a.get("title") or "", b.get("title") or "") >= 0.35
        return _shared_root_or_evidence(a, b)

    def is_similar_different(a: dict, b: dict) -> bool:
        """Only when themes overlap AND there is some shared root/evidence, but mechanisms differ.

        Must NOT fire on shared category 「混杂」 alone (e.g. 海藻糖对照 vs 台面—水分).
        """
        if is_true_duplicate(a, b):
            return False
        ta, tb = themes_of(a.get("title") or ""), themes_of(b.get("title") or "")
        shared = ta & tb
        if not shared:
            return False
        # Forbidden: link solely on 混杂
        if shared <= {"混杂"}:
            return False
        ga, gb = _root_groups(a), _root_groups(b)
        # Different explicit root-cause groups → independent (no relation)
        if ga and gb and not (ga & gb):
            return False
        # Need either shared root or substantial overlap to even mark similar
        if not _shared_root_or_evidence(a, b):
            return False
        # Shared broad/specific theme with overlapping root but different emphasis
        return bool(shared & (BROAD | SPECIFIC))

    dup_group_i = 1
    for f in llm_findings:
        t = f.get("title") or ""
        if re_search_blank_missing(t):
            continue
        nf = dict(f)
        nf.setdefault("duplicate_relation", "none")
        related = None
        relation = "none"
        for ex in merged:
            if is_true_duplicate(ex, nf):
                related, relation = ex, "true_duplicate"
                break
            if related is None and is_similar_different(ex, nf):
                related, relation = ex, "similar_different_mechanism"
        if related is not None and relation != "none":
            gid = related.get("duplicate_group") or f"DG{dup_group_i:02d}"
            if not related.get("duplicate_group"):
                related["duplicate_group"] = gid
                dup_group_i += 1
            reason = (
                f"与 {related.get('id')} 共享根因/证据且同维度，疑似同一缺陷的规则/LLM 双源表述"
                if relation == "true_duplicate"
                else f"与 {related.get('id')} 有证据重叠但机制侧重点不同，保留两条并标注关联"
            )
            nf["duplicate_of"] = related.get("id")
            nf["duplicate_group"] = gid
            nf["duplicate_reason"] = reason
            nf["duplicate_relation"] = relation
            if related.get("duplicate_relation") in (None, "none"):
                related["duplicate_relation"] = relation
                related["duplicate_group"] = gid
                related["duplicate_reason"] = (
                    f"后续条目将与本条归组（{relation}）；本条保留为优先展示源之一"
                )
        merged.append(nf)

    # renumber F ids; keep rule_id for CE/optimizer; rewrite duplicate_of to new ids via map
    old_ids = [f.get("id") for f in merged]
    out = []
    id_map = {}
    for i, f in enumerate(merged, start=1):
        nf = dict(f)
        new_id = f"F{i:02d}"
        id_map[old_ids[i - 1]] = new_id
        id_map[f.get("id")] = new_id
        nf["id"] = new_id
        out.append(nf)
    for nf in out:
        dup = nf.get("duplicate_of")
        if dup and dup in id_map:
            nf["duplicate_of"] = id_map[dup]
    return out
