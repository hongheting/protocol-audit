#!/usr/bin/env python3
"""V0.1.2 full real-LLM regression for trial1 + trial2. Not for production CI."""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.pipeline import build_parse_preview, run_audit, public_preview
from protocol_audit.schema_validate import validate

SHANGHAI = timezone(timedelta(hours=8))
OUT = ROOT / "real-trials" / "regression-v012"
LOG = ROOT / "logs" / "llm" / f"calls-{datetime.now(SHANGHAI).strftime('%Y%m%d')}.jsonl"


def now() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def log_offset() -> int:
    if not LOG.is_file():
        return 0
    return sum(1 for _ in LOG.open())


def read_new_calls(start: int) -> list[dict]:
    if not LOG.is_file():
        return []
    lines = LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[start:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize_calls(calls: list[dict]) -> dict:
    ok = [c for c in calls if c.get("ok")]
    fail = [c for c in calls if not c.get("ok")]
    tokens = {
        "prompt": sum((c.get("prompt_tokens") or 0) for c in calls),
        "completion": sum((c.get("completion_tokens") or 0) for c in calls),
        "reasoning": sum((c.get("reasoning_tokens") or 0) for c in calls),
        "total": sum(((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0)) for c in calls),
    }
    return {
        "n_calls": len(calls),
        "n_ok": len(ok),
        "n_fail": len(fail),
        "fail_errors": [c.get("error") for c in fail],
        "latency_ms_sum": sum(c.get("latency_ms") or 0 for c in calls),
        "purposes": [c.get("purpose") for c in calls],
        "models": sorted({c.get("model") for c in calls if c.get("model")}),
        "tokens": tokens,
        "cost": "未知（日志无单价；仅有 token 计数若 API 返回）",
        "calls": [
            {
                "ts": c.get("ts"),
                "purpose": c.get("purpose"),
                "ok": c.get("ok"),
                "model": c.get("model"),
                "latency_ms": c.get("latency_ms"),
                "prompt_tokens": c.get("prompt_tokens"),
                "completion_tokens": c.get("completion_tokens"),
                "error": c.get("error"),
            }
            for c in calls
        ],
    }


def run_one(trial: str, docx: Path) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    start_off = log_offset()
    t0 = time.time()
    meta = {
        "trial": trial,
        "source": str(docx),
        "started_at": now(),
        "mode": "LLM实测",
        "provider_requested": "glm",
        "model_requested": "glm-4.6",
    }
    print(f"=== START {trial} @ {meta['started_at']} ===", flush=True)
    try:
        preview = build_parse_preview(
            path=docx,
            research_goal_level="unspecified",
            use_llm_parse=True,
            llm_provider="glm",
        )
        # Save full design extract before stripping
        design_full = preview.get("_design_full") or {}
        extract = design_full.get("_llm_extract") or preview.get("_llm_extract")
        llm_meta = preview.get("_llm_meta") or design_full.get("_llm_meta")
        (OUT / f"{trial}.parse-preview.json").write_text(
            json.dumps(public_preview(preview), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / f"{trial}.design-extract.json").write_text(
            json.dumps(
                {
                    "llm_meta": llm_meta,
                    "design_extract": extract,
                    "hypotheses": (design_full.get("hypotheses") or design_full.get("claims") or []),
                    "groups": design_full.get("groups"),
                    "endpoints": design_full.get("endpoints"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
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
        (OUT / f"{trial}.audit-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # CLI-style summary text
        lines = [
            f"source: {docx}",
            f"goal: {report.get('research_goal_level')} {report.get('research_goal_level_source')}",
            f"boundary: {(report.get('boundary_note') or '')[:300]}",
            f"verdict: {report['summary']['verdict']} | {report['summary']['one_liner']}",
            f"findings: {len(report['findings'])} confirmed {report['summary']['confirmed_count']} needs_info {report['summary']['needs_info_count']} suggestion {report['summary']['suggestion_count']}",
        ]
        for f in report["findings"]:
            lines.append(f"  - {f['id']} [{f['category']}/{f['severity']}] {f['title']}")
        lines.append(f"questions: {len(report.get('clarifying_questions') or [])}")
        lines.append(f"CE rows: {len(report['claim_evidence_map']['rows'])}")
        for r in report["claim_evidence_map"]["rows"]:
            lines.append(f"  - {r.get('id')} supports={r.get('design_supports')} | {(r.get('claim') or '')[:120]}")
        lines.append(f"Plan A notes: {len(report['optimizer']['change_notes'])}")
        for n in report["optimizer"]["change_notes"]:
            lines.append(f"  - {n['id']}: {(n.get('summary') or '')[:160]}")
        lines.append(f"schema_errors: {errs or 'OK'}")
        (OUT / f"{trial}.cli-summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines), flush=True)

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
                "llm_calls": call_sum,
                "parse_llm_ok": bool((llm_meta or {}).get("ok")),
                "review_llm_ok": bool((report.get("llm_review_meta") or report.get("_llm_review_meta") or {}).get("ok"))
                if False
                else None,
            }
        )
        # try to find review meta on report
        for key in ("llm_meta", "review_meta", "engine_meta"):
            if key in report:
                meta[f"report_{key}"] = report[key]
        # boundary often embeds review status
        meta["boundary_note"] = report.get("boundary_note")
        (OUT / f"{trial}.call-summary.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"=== DONE {trial} wall={meta['wall_s']}s calls={call_sum['n_calls']} ok={call_sum['n_ok']} fail={call_sum['n_fail']} ===", flush=True)
        return meta
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
        (OUT / f"{trial}.call-summary.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"=== FAIL {trial}: {e} ===", flush=True)
        traceback.print_exc()
        return meta


def main() -> int:
    trials = [
        ("trial1", ROOT / "real-trials" / "trial1.docx"),
        ("trial2", ROOT / "real-trials" / "trial2.docx"),
    ]
    which = sys.argv[1:] or ["trial1", "trial2"]
    results = []
    for name, path in trials:
        if name not in which:
            continue
        if not path.is_file():
            print(f"MISSING {path}", flush=True)
            results.append({"trial": name, "ok": False, "error": "missing docx"})
            continue
        results.append(run_one(name, path))
    (OUT / "run-meta.json").write_text(
        json.dumps({"finished_at": now(), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
