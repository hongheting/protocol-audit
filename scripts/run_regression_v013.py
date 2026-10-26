#!/usr/bin/env python3
"""V0.1.3 offline regression: rules + CE + Plan A replay (no scientific Prompt change).

Pass types labeled per check: 规则测试 / 离线重放 / (optional) 真实LLM实测.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit import __version__
from protocol_audit.claim_evidence import build_claim_evidence_map
from protocol_audit.llm_parse import SYSTEM_PROMPT as DESIGN_SYSTEM
from protocol_audit.llm_parse import merge_llm_into_design
from protocol_audit.llm_review import SYSTEM as REVIEW_SYSTEM
from protocol_audit.optimizer_a import build_group_table, plan_a
from protocol_audit.rules import run_rules
from protocol_audit.schema_validate import validate

SH = timezone(timedelta(hours=8))
OUT = ROOT / "real-trials" / "regression-v013"
FREEZE_DESIGN = "241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b"
FREEZE_REVIEW = "26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def design_from_extract(extract_path: Path, full_text: str) -> dict:
    extract = load_json(extract_path)
    # design-extract may be wrapped
    if "hypotheses" not in extract and "design_extract" in extract:
        extract = extract["design_extract"]
    heuristic = {
        "groups": [],
        "research_goal_level": "unspecified",
        "research_goal_level_source": "default",
        "hypotheses": [],
        "controls": [],
        "outcomes": [],
        "replication": {},
        "claims": [],
        "field_meta": {},
        "statistical_plan": "",
    }
    return merge_llm_into_design(heuristic, extract)


def covered_ids(plan: dict) -> set[str]:
    s: set[str] = set()
    for n in plan.get("change_notes") or []:
        s.update(n.get("addresses_finding_ids") or [])
    return s


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(SH).isoformat(timespec="seconds")
    report: dict = {
        "version": __version__,
        "generated_at": now,
        "prompt_hashes": {
            "design_extract": sha(DESIGN_SYSTEM),
            "scientific_review": sha(REVIEW_SYSTEM),
            "matches_freeze": sha(DESIGN_SYSTEM) == FREEZE_DESIGN
            and sha(REVIEW_SYSTEM) == FREEZE_REVIEW,
        },
        "trials": {},
    }
    assert report["prompt_hashes"]["matches_freeze"], report["prompt_hashes"]

    # --- Trial 1: offline Plan A on saved findings + structural on extract ---
    t1_raw = (ROOT / "real-trials" / "trial1_raw.txt").read_text(encoding="utf-8")
    t1_extract = ROOT / "real-trials" / "regression-v012" / "trial1.design-extract.json"
    t1_report = load_json(ROOT / "real-trials" / "regression-v012" / "trial1.audit-report.json")
    d1 = design_from_extract(t1_extract, t1_raw)
    rules1 = run_rules(d1, source_file="trial1.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", full_text=t1_raw)
    plan1_rules = plan_a(d1, rules1["findings"], build_group_table(d1))
    plan1_saved = plan_a(d1, t1_report["findings"], build_group_table(d1))
    notes1 = " ".join(n["summary"] for n in plan1_saved["change_notes"])
    t1 = {
        "pass_type": "离线重放",
        "structural_rule_ids": sorted(
            {f.get("rule_id") for f in rules1["findings"] if f.get("rule_id")}
        ),
        "plan_a_from_saved_findings": {
            "optimizer_incomplete": plan1_saved.get("optimizer_incomplete"),
            "blocker_action_map": plan1_saved.get("blocker_action_map"),
            "change_note_summaries": [n["summary"] for n in plan1_saved["change_notes"]],
            "tank_level_repeat_ok": ("水槽" in notes1)
            and ("统计模型" in notes1 or "ANOVA" in notes1 or "不可仅" in notes1),
        },
        "plan_a_from_rules_only": {
            "optimizer_incomplete": plan1_rules.get("optimizer_incomplete"),
            "blocker_count": sum(
                1
                for f in rules1["findings"]
                if f.get("category") == "confirmed" and f.get("severity") == "blocker"
            ),
        },
    }
    report["trials"]["trial1"] = t1

    # --- Trial 2 ---
    t2_raw = (ROOT / "real-trials" / "trial2.source-note.txt").read_text(encoding="utf-8")
    # prefer raw if large; else use audit text from report quotes — try llm extract companion
    raw2_candidates = [
        ROOT / "real-trials" / "trial2_raw.txt",
        ROOT / "real-trials" / "trial2.source-note.txt",
    ]
    t2_text = ""
    for c in raw2_candidates:
        if c.exists() and c.stat().st_size > 100:
            t2_text = c.read_text(encoding="utf-8")
            break
    if len(t2_text) < 500:
        # reconstruct soft text from saved report quotes
        t2_rep = load_json(ROOT / "real-trials" / "regression-v012" / "trial2.audit-report.json")
        bits = []
        for f in t2_rep.get("findings") or []:
            for loc in f.get("locations") or []:
                if loc.get("quote"):
                    bits.append(loc["quote"])
        t2_text = "\n".join(bits) + "\n" + t2_text
    t2_extract = ROOT / "real-trials" / "regression-v012" / "trial2.design-extract.json"
    t2_report = load_json(ROOT / "real-trials" / "regression-v012" / "trial2.audit-report.json")
    d2 = design_from_extract(t2_extract, t2_text)
    rules2 = run_rules(d2, source_file="trial2.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", full_text=t2_text)
    plan2 = plan_a(d2, t2_report["findings"], build_group_table(d2))
    blob2 = str(plan2)
    report["trials"]["trial2"] = {
        "pass_type": "离线重放",
        "no_trial1_bleed": all(x not in blob2 for x in ("挂板", "水槽", "UV-C", "润湿")),
        "optimizer_incomplete": plan2.get("optimizer_incomplete"),
        "blocker_action_map": plan2.get("blocker_action_map"),
        "structural_rule_ids": sorted(
            {f.get("rule_id") for f in rules2["findings"] if f.get("rule_id")}
        ),
        "change_notes": [n["summary"] for n in plan2["change_notes"]],
    }

    # --- Trial 3: key acceptance ---
    t3_raw = (ROOT / "real-trials" / "blind-trial3" / "trial3_raw.txt").read_text(
        encoding="utf-8"
    )
    t3_extract = ROOT / "real-trials" / "blind-trial3" / "design-extract.json"
    t3_report = load_json(ROOT / "real-trials" / "blind-trial3" / "audit-report.json")
    d3 = design_from_extract(t3_extract, t3_raw)
    rules3 = run_rules(d3, source_file="trial3.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", full_text=t3_raw)
    # Plan A on ORIGINAL blind findings (F03/F04 coverage)
    plan3 = plan_a(d3, t3_report["findings"], build_group_table(d3))
    cov = covered_ids(plan3)
    # Fresh structural should add representative + single batch
    rule_ids3 = {f.get("rule_id") for f in rules3["findings"] if f.get("rule_id")}
    titles3 = [f["title"] for f in rules3["findings"]]
    ce3 = build_claim_evidence_map(
        d3,
        source_file="trial3.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        full_text=t3_raw,
        findings=rules3["findings"] + t3_report["findings"],
    )
    # schema check on a minimal optimizer payload
    mini = {
        "schema_version": "0.2.1",
        "discipline_resolved": "environmental",
        "boundary_note": "regression",
        "research_goal_level": "unspecified",
        "research_goal_level_source": "default",
        "ingest_manifest": {
            "source_file": "trial3.docx",
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "parse_warnings": [],
            "blocks_count": 0,
            "tables_count": 0,
            "unparsed_assets": [],
        },
        "design_confirmation": {"status": "confirmed", "confirmed_at": now, "notes": ""},
        "summary": t3_report["summary"],
        "identification": t3_report["identification"],
        "claim_evidence_map": ce3,
        "clarifying_questions": rules3["clarifying_questions"],
        "findings": t3_report["findings"],
        "optimizer": plan3,
        "group_table": build_group_table(d3),
        "literature_hints": [],
        "reverse_review": t3_report.get("reverse_review")
        or {
            "enabled": False,
            "status": "deferred_v0_2",
            "preview_strongest_claim": "",
            "note": "",
        },
        "privacy_applied": {
            "public_literature_search_used": False,
            "note": "V0.1.3 regression",
        },
        "limited_audit": False,
        "coverage_note": "offline",
    }
    # strip non-schema from findings for validate
    clean_f = []
    for f in mini["findings"]:
        clean_f.append(
            {
                k: v
                for k, v in f.items()
                if k
                in {
                    "id",
                    "dimension",
                    "severity",
                    "category",
                    "title",
                    "locations",
                    "why_invalidates",
                    "fix",
                    "evidence_class",
                    "evidence_refs",
                    "estimated_burden",
                    "hard_error",
                    "search_keywords",
                    "related_group_ids",
                    "related_claim_ids",
                    "duplicate_of",
                    "duplicate_group",
                    "duplicate_reason",
                    "duplicate_relation",
                }
            }
        )
    mini["findings"] = clean_f
    schema_errs = validate("report", mini)

    report["trials"]["trial3"] = {
        "pass_type": "离线重放（Plan A 对盲测 saved findings）+ 规则测试（代表盆/单批次）",
        "F03_covered": "F03" in cov,
        "F04_covered": "F04" in cov,
        "blocker_coverage_rate": (
            sum(1 for m in plan3.get("blocker_action_map") or [] if m.get("covered"))
            / max(1, len(plan3.get("blocker_action_map") or []))
        ),
        "optimizer_incomplete": plan3.get("optimizer_incomplete"),
        "blocker_action_map": plan3.get("blocker_action_map"),
        "change_notes": [
            {"id": n["id"], "addresses": n.get("addresses_finding_ids"), "summary": n["summary"]}
            for n in plan3["change_notes"]
        ],
        "new_rules_hit": {
            "representative_unit": "structural_representative_unit_dosing" in rule_ids3,
            "single_batch": "structural_single_batch_material" in rule_ids3,
            "titles": titles3,
        },
        "no_bleed": all(
            x not in str(plan3) + str(ce3) for x in ("UV-C", "挂板", "水槽润湿")
        ),
        "schema_errors_sample": schema_errs[:8],
        "schema_ok": not schema_errs,
    }

    # Persist artifacts
    (OUT / "regression-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "trial3.plan_a.v013.json").write_text(
        json.dumps(plan3, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "trial1.plan_a.v013.json").write_text(
        json.dumps(plan1_saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "trial3.rules.v013.json").write_text(
        json.dumps(
            {
                "findings": [
                    {k: f.get(k) for k in ("id", "rule_id", "category", "severity", "title")}
                    for f in rules3["findings"]
                ],
                "questions": rules3["clarifying_questions"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps({"ok": True, "version": __version__, "out": str(OUT), **report["prompt_hashes"]}, ensure_ascii=False))
    print("T1 tank_ok", t1["plan_a_from_saved_findings"]["tank_level_repeat_ok"])
    print("T3 F03/F04", report["trials"]["trial3"]["F03_covered"], report["trials"]["trial3"]["F04_covered"])
    print("T3 new rules", report["trials"]["trial3"]["new_rules_hit"])
    print("schema_ok", report["trials"]["trial3"]["schema_ok"], schema_errs[:3])
    return 0 if (
        t1["plan_a_from_saved_findings"]["tank_level_repeat_ok"]
        and report["trials"]["trial3"]["F03_covered"]
        and report["trials"]["trial3"]["F04_covered"]
        and report["trials"]["trial3"]["new_rules_hit"]["representative_unit"]
        and report["trials"]["trial3"]["new_rules_hit"]["single_batch"]
        and report["prompt_hashes"]["matches_freeze"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
