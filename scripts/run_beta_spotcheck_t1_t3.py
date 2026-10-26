#!/usr/bin/env python3
"""Beta spotcheck: Trial1 + Trial3 one real-LLM run each. Science Prompt frozen. No gold injection / no tuning."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit import __version__
from protocol_audit.llm_parse import LLMParseError
from protocol_audit.pipeline import build_parse_preview, run_audit, public_preview
from protocol_audit.review_windows import build_review_windows
from protocol_audit.schema_validate import validate
from protocol_audit.rules import run_rules
from protocol_audit.rules_structural import adjust_extrapolation_severity

SHANGHAI = timezone(timedelta(hours=8))
OUT_ROOT = ROOT / "real-trials" / "beta-spotcheck-t1-t3"
LOG = ROOT / "logs" / "llm" / f"calls-{datetime.now(SHANGHAI).strftime('%Y%m%d')}.jsonl"
FREEZE = {
    "design_extract": "241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b",
    "scientific_review": "26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705",
}
TRIALS = {
    "trial1": ROOT / "real-trials" / "trial1.docx",
    "trial3": ROOT / "real-trials" / "trial3.docx",
}


def now() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def prompt_body_hash(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"{name}\s*=\s*\"\"\"(.*?)\"\"\"", text, re.S)
    if not m:
        raise RuntimeError(f"const {name} missing in {path}")
    return hashlib.sha256(m.group(1).encode()).hexdigest()


def log_offset() -> int:
    if not LOG.is_file():
        return 0
    return sum(1 for _ in LOG.open())


def read_new_calls(start: int) -> list[dict]:
    if not LOG.is_file():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines()[start:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize_calls(calls: list[dict]) -> dict:
    ok = [c for c in calls if c.get("ok")]
    fail = [c for c in calls if not c.get("ok")]
    expand = [
        c for c in calls
        if c.get("purpose") in ("design_extract_expand_retry", "scientific_review_expand_retry")
        or str(c.get("purpose") or "").endswith("_expand_retry")
    ]
    return {
        "n_calls": len(calls),
        "n_ok": len(ok),
        "n_fail": len(fail),
        "n_expand_retry": len(expand),
        "fail_errors": [c.get("error") for c in fail],
        "latency_ms_sum": sum(c.get("latency_ms") or 0 for c in calls),
        "purposes": [c.get("purpose") for c in calls],
        "models": sorted({c.get("model") for c in calls if c.get("model")}),
        "finish_reasons": [c.get("finish_reason") for c in calls],
        "tokens": {
            "prompt": sum((c.get("prompt_tokens") or 0) for c in calls),
            "completion": sum((c.get("completion_tokens") or 0) for c in calls),
            "reasoning": sum((c.get("reasoning_tokens") or 0) for c in calls),
            "total": sum(((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0)) for c in calls),
        },
        "calls": [
            {
                "ts": c.get("ts"),
                "purpose": c.get("purpose"),
                "ok": c.get("ok"),
                "model": c.get("model"),
                "latency_ms": c.get("latency_ms"),
                "prompt_tokens": c.get("prompt_tokens"),
                "completion_tokens": c.get("completion_tokens"),
                "finish_reason": c.get("finish_reason"),
                "max_tokens": c.get("max_tokens"),
                "error": c.get("error"),
            }
            for c in calls
        ],
    }


def write_review_windows(full_text: str, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    windows, coverage = build_review_windows(full_text or "")
    cov = coverage.to_dict()
    (dest / "full_text_extract.txt").write_text(full_text, encoding="utf-8")
    (dest / "review_coverage.json").write_text(
        json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for w in windows:
        (dest / f"sent_{w.window_id}.txt").write_text(w.text, encoding="utf-8")
        (dest / f"sent_{w.window_id}.meta.json").write_text(
            json.dumps(w.meta(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cov


def rules_only_titles(design, full_text, source_file, media_type):
    out = run_rules(design, source_file=source_file, media_type=media_type, full_text=full_text)
    findings = adjust_extrapolation_severity(out["findings"], full_text)
    return [(f.get("title"), f.get("category"), f.get("severity"), f.get("rule_id")) for f in findings]


def run_one(trial_id: str, docx: Path) -> int:
    OUT = OUT_ROOT / trial_id
    OUT.mkdir(parents=True, exist_ok=True)
    run_log = (OUT / "run.log").open("w", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        run_log.write(line + "\n")
        run_log.flush()

    prompt_hashes = {
        "design_extract": prompt_body_hash(ROOT / "protocol_audit" / "llm_parse.py", "SYSTEM_PROMPT"),
        "scientific_review": prompt_body_hash(ROOT / "protocol_audit" / "llm_review.py", "SYSTEM"),
    }
    meta = {
        "trial": trial_id,
        "mode": "Beta-spotcheck-real-LLM",
        "code_version": __version__,
        "science_freeze": "V0.1.2",
        "no_tuning": True,
        "no_gold_injected": True,
        "prompt_hashes": prompt_hashes,
        "prompt_match_v012_freeze": prompt_hashes == FREEZE,
        "source": str(docx),
        "started_at": now(),
        "provider_requested": "glm",
        "model_requested": "glm-4.6",
    }
    (OUT / "run-meta-start.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"START {trial_id} version={__version__} prompt_match={meta['prompt_match_v012_freeze']}")

    if not docx.is_file():
        log(f"MISSING {docx}")
        run_log.close()
        return 1
    if not meta["prompt_match_v012_freeze"]:
        log(f"PROMPT HASH MISMATCH: {prompt_hashes}")
        run_log.close()
        return 4

    start_off = log_offset()
    t0 = time.time()
    try:
        preview = build_parse_preview(
            path=docx,
            research_goal_level="unspecified",
            use_llm_parse=True,
            llm_provider="glm",
        )
        design_full = preview.get("_design_full") or {}
        extract = design_full.get("_llm_extract")
        llm_meta = preview.get("_llm_meta") or design_full.get("_llm_meta")
        full_text = preview.get("_full_text") or "\n\n".join(
            b.get("text") or "" for b in (preview.get("ingested_blocks") or [])
        )
        media_type = preview.get("media_type") or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        cov = write_review_windows(full_text, OUT / "review-artifacts")
        log(
            f"review_windows n={cov.get('n_windows')} comprehensive={cov.get('comprehensive')} "
            f"methods_detected={cov.get('methods_detected')} truncated={cov.get('truncated')}"
        )

        (OUT / "parse-preview.json").write_text(
            json.dumps(public_preview(preview), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / "design-extract.json").write_text(
            json.dumps({"llm_meta": llm_meta, "design_extract": extract}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log(
            f"parse ok={bool((llm_meta or {}).get('ok'))} expand={bool((llm_meta or {}).get('expanded_retry'))} "
            f"finish={(llm_meta or {}).get('finish_reason')} hard_fail={bool((llm_meta or {}).get('hard_fail'))}"
        )

        rule_titles = rules_only_titles(design_full, full_text, docx.name, media_type)
        (OUT / "rules-only-findings.json").write_text(
            json.dumps(rule_titles, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        report = run_audit(
            preview,
            confirm_design=True,
            research_goal_level="unspecified",
            discipline="auto",
            use_llm_review=True,
            llm_provider="glm",
        )
        errs = validate("report", report)
        (OUT / "audit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "schema-errors.json").write_text(json.dumps(errs, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"schema_errors={len(errs)} findings={len(report.get('findings') or [])}")

        elapsed = time.time() - t0
        calls = read_new_calls(start_off)
        call_sum = summarize_calls(calls)

        findings = report.get("findings") or []
        by_origin: dict[str, list] = {}
        for f in findings:
            o = f.get("origin") or "unknown"
            by_origin.setdefault(o, []).append(f.get("title"))
        rule_set = {t[0] for t in rule_titles}
        all_titles = {f.get("title") for f in findings}
        new_vs_rules = sorted(all_titles - rule_set)

        # Completeness / facade check
        boundary = report.get("boundary_note") or ""
        pretend = False
        review_status = None
        # pull from boundary heuristics + call finish reasons
        frs = call_sum.get("finish_reasons") or []
        llm_origin_n = len(by_origin.get("llm_review") or [])
        if "部分" in boundary or "失败" in boundary or "不得将本次报告视为完整" in boundary:
            review_hint = "partial_or_failed_declared"
        else:
            review_hint = "appears_complete_or_rules"
        # silent facade: zero llm findings + complete-looking + length truncate without expand success
        if llm_origin_n == 0 and any(x in ("length", "max_tokens") for x in frs if x):
            pretend = True

        summary = {
            **meta,
            "finished_at": now(),
            "elapsed_s": round(elapsed, 1),
            "schema_ok": len(errs) == 0,
            "schema_errors": errs,
            "boundary_note": boundary,
            "coverage_note": report.get("coverage_note"),
            "summary": report.get("summary"),
            "findings_brief": [
                {
                    "id": f.get("id"),
                    "origin": f.get("origin"),
                    "category": f.get("category"),
                    "severity": f.get("severity"),
                    "title": f.get("title"),
                    "duplicate_relation": f.get("duplicate_relation"),
                }
                for f in findings
            ],
            "origin_counts": {k: len(v) for k, v in by_origin.items()},
            "rules_only_count": len(rule_titles),
            "llm_incremental_titles": new_vs_rules,
            "facade_risk_flag": pretend,
            "review_hint": review_hint,
            "ce_brief": [
                {
                    "id": r.get("id"),
                    "hypothesis_id": r.get("hypothesis_id"),
                    "row_kind": r.get("row_kind"),
                    "design_supports": r.get("design_supports"),
                    "claim": (r.get("claim") or "")[:160],
                }
                for r in (report.get("claim_evidence_map") or {}).get("rows") or []
            ],
            "optimizer": {
                "optimizer_incomplete": (report.get("optimizer") or {}).get("optimizer_incomplete"),
                "blocker_action_map": (report.get("optimizer") or {}).get("blocker_action_map"),
                "change_notes": [
                    {
                        "id": c.get("id"),
                        "addresses_finding_ids": c.get("addresses_finding_ids"),
                        "summary": (c.get("summary") or c.get("text") or "")[:200],
                    }
                    for c in ((report.get("optimizer") or {}).get("change_notes") or [])
                ],
            },
            "clarifying_questions_n": len(report.get("clarifying_questions") or []),
            "calls": call_sum,
            "review_coverage": cov,
        }
        (OUT / "call-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        lines = [
            f"{trial_id} Beta-spotcheck finished={now()} elapsed={elapsed:.1f}s",
            f"prompt_match={meta['prompt_match_v012_freeze']} schema_ok={len(errs)==0}",
            f"findings={len(findings)} origins={summary['origin_counts']} facade_risk={pretend}",
            f"calls={call_sum['n_calls']} expand={call_sum['n_expand_retry']} finish={call_sum['finish_reasons']}",
            f"PlanA incomplete={(report.get('optimizer') or {}).get('optimizer_incomplete')}",
            f"boundary={boundary[:280]}",
        ]
        (OUT / "cli-summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log("DONE " + " | ".join(lines[:4]))
        run_log.close()
        return 0 if not errs else 2
    except LLMParseError as e:
        log(f"PARSE HARD FAIL: {e}")
        traceback.print_exc()
        (OUT / "hard-fail.json").write_text(
            json.dumps({"error": str(e), "at": now()}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        run_log.close()
        return 3
    except Exception as e:
        log(f"FAIL: {e}")
        traceback.print_exc()
        run_log.close()
        return 1


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    ids = ["trial1", "trial3"] if which == "both" else [which]
    rc = 0
    for tid in ids:
        docx = TRIALS.get(tid)
        if not docx:
            print(f"unknown trial {tid}", flush=True)
            return 1
        r = run_one(tid, docx)
        if r != 0:
            rc = r
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
