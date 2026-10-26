#!/usr/bin/env python3
"""Trial 3 full real-LLM regression under V0.1.3.1 (science Prompt frozen at V0.1.2; postprocess fixes). No gold injection."""
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
from protocol_audit.schema_validate import validate

SHANGHAI = timezone(timedelta(hours=8))
OUT = ROOT / "real-trials" / "regression-v0131-llm" / "trial3"
LOG = ROOT / "logs" / "llm" / f"calls-{datetime.now(SHANGHAI).strftime('%Y%m%d')}.jsonl"
DOCX = ROOT / "real-trials" / "trial3.docx"


def now() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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
    expand = [c for c in calls if c.get("purpose") == "design_extract_expand_retry"]
    return {
        "n_calls": len(calls),
        "n_ok": len(ok),
        "n_fail": len(fail),
        "n_expand_retry": len(expand),
        "fail_errors": [c.get("error") for c in fail],
        "latency_ms_sum": sum(c.get("latency_ms") or 0 for c in calls),
        "purposes": [c.get("purpose") for c in calls],
        "models": sorted({c.get("model") for c in calls if c.get("model")}),
        "tokens": {
            "prompt": sum((c.get("prompt_tokens") or 0) for c in calls),
            "completion": sum((c.get("completion_tokens") or 0) for c in calls),
            "reasoning": sum((c.get("reasoning_tokens") or 0) for c in calls),
            "total": sum(((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0)) for c in calls),
        },
        "cost": "未知（未配置单价表；仅记录 token）",
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


def main() -> int:
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
    freeze = {
        "design_extract": "241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b",
        "scientific_review": "26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705",
    }
    meta = {
        "trial": "trial3",
        "mode": "LLM实测-回归-V0.1.3.1",
        "code_version": __version__,
        "science_freeze": "V0.1.2",
        "reliability_patch": "V0.1.2.1",
        "rules_postprocess": "V0.1.3.1",
        "prompt_hashes": prompt_hashes,
        "prompt_match_v012_freeze": prompt_hashes == freeze,
        "file_hashes": {
            "llm_parse.py": sha_file(ROOT / "protocol_audit" / "llm_parse.py"),
            "llm_review.py": sha_file(ROOT / "protocol_audit" / "llm_review.py"),
            "llm_client.py": sha_file(ROOT / "protocol_audit" / "llm_client.py"),
            "pipeline.py": sha_file(ROOT / "protocol_audit" / "pipeline.py"),
            "rules_structural.py": sha_file(ROOT / "protocol_audit" / "rules_structural.py"),
            "claim_evidence.py": sha_file(ROOT / "protocol_audit" / "claim_evidence.py"),
            "optimizer_a.py": sha_file(ROOT / "protocol_audit" / "optimizer_a.py"),
            "report.py": sha_file(ROOT / "protocol_audit" / "report.py"),
            "rules.py": sha_file(ROOT / "protocol_audit" / "rules.py"),
        },
        "source": str(DOCX),
        "started_at": now(),
        "provider_requested": "glm",
        "model_requested": "glm-4.6",
        "no_gold_injected": True,
        "no_trial3_specific_rules": True,
    }
    (OUT / "run-meta-start.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"START trial3-v0131-llm version={__version__} prompt_match={meta['prompt_match_v012_freeze']}")

    if not DOCX.is_file():
        log(f"MISSING {DOCX}")
        return 1

    start_off = log_offset()
    t0 = time.time()
    try:
        preview = build_parse_preview(
            path=DOCX,
            research_goal_level="unspecified",
            use_llm_parse=True,
            llm_provider="glm",
        )
        design_full = preview.get("_design_full") or {}
        extract = design_full.get("_llm_extract")
        llm_meta = preview.get("_llm_meta") or design_full.get("_llm_meta")
        (OUT / "parse-preview.json").write_text(
            json.dumps(public_preview(preview), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / "design-extract.json").write_text(
            json.dumps({"llm_meta": llm_meta, "design_extract": extract}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log(f"parse ok={bool((llm_meta or {}).get('ok'))} expand={bool((llm_meta or {}).get('expanded_retry'))} hard_fail={bool((llm_meta or {}).get('hard_fail'))}")

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

        lines = [
            f"source: {DOCX}",
            f"version: {__version__}",
            f"goal: {report.get('research_goal_level')} {report.get('research_goal_level_source')}",
            f"boundary: {(report.get('boundary_note') or '')[:400]}",
            f"verdict: {report['summary']['verdict']} | {report['summary']['one_liner']}",
            f"findings: {len(report['findings'])} confirmed {report['summary']['confirmed_count']} needs_info {report['summary']['needs_info_count']} suggestion {report['summary']['suggestion_count']}",
        ]
        for f in report["findings"]:
            lines.append(
                f"  - {f['id']} [{f['category']}/{f['severity']}] rule={f.get('rule_id') or f.get('source') or ''} | {f['title']}"
            )
        lines.append(f"CE rows: {len(report['claim_evidence_map']['rows'])}")
        for r in report["claim_evidence_map"]["rows"]:
            lines.append(f"  - {r.get('id')} supports={r.get('design_supports')} | {(r.get('claim') or '')[:140]}")
        lines.append(f"Plan A notes: {len(report['optimizer']['change_notes'])}")
        for n in report["optimizer"]["change_notes"]:
            lines.append(f"  - {n['id']}: {(n.get('summary') or '')[:200]}")
        lines.append(f"schema_errors: {errs or 'OK'}")
        (OUT / "cli-summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log("\n".join(lines))

        calls = read_new_calls(start_off)
        call_sum = summarize_calls(calls)
        meta.update(
            {
                "finished_at": now(),
                "wall_s": round(time.time() - t0, 1),
                "ok": True,
                "schema_ok": not errs,
                "schema_errors": errs,
                "n_findings": len(report["findings"]),
                "confirmed": report["summary"]["confirmed_count"],
                "needs_info": report["summary"]["needs_info_count"],
                "verdict": report["summary"]["verdict"],
                "boundary_note": report.get("boundary_note"),
                "parse_llm_meta": {
                    k: (llm_meta or {}).get(k)
                    for k in (
                        "ok",
                        "hard_fail",
                        "fallback",
                        "truncation_detected",
                        "expanded_retry",
                        "max_tokens_initial",
                        "max_tokens_used",
                        "error",
                        "attempts",
                    )
                },
                "llm_calls": call_sum,
            }
        )
        (OUT / "call-summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"DONE wall={meta['wall_s']}s calls={call_sum['n_calls']} expand={call_sum['n_expand_retry']}")
        run_log.close()
        return 0 if not errs else 2
    except LLMParseError as e:
        calls = read_new_calls(start_off)
        meta.update(
            {
                "finished_at": now(),
                "wall_s": round(time.time() - t0, 1),
                "ok": False,
                "error": f"LLMParseError: {e}",
                "parse_llm_meta": e.llm_meta,
                "llm_calls": summarize_calls(calls),
            }
        )
        (OUT / "call-summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"HARD FAIL parse: {e}")
        run_log.close()
        return 3
    except Exception as e:
        calls = read_new_calls(start_off)
        meta.update(
            {
                "finished_at": now(),
                "wall_s": round(time.time() - t0, 1),
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
                "llm_calls": summarize_calls(calls),
            }
        )
        (OUT / "call-summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"FAIL: {e}")
        traceback.print_exc()
        run_log.close()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
