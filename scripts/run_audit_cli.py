#!/usr/bin/env python3
"""CLI: audit a protocol file and print summary + write report JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_audit.pipeline import audit_file
from protocol_audit.schema_validate import validate


def main() -> int:
    ap = argparse.ArgumentParser(description="ProtocolAudit V0.1.2.1 CLI")
    ap.add_argument("path", type=Path)
    ap.add_argument("--goal", default="unspecified")
    ap.add_argument("--discipline", default="auto")
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--llm", choices=["off", "glm", "gemini", "auto"], default="auto",
                    help="LLM provider for parse+review (auto=glm if key else off)")
    ap.add_argument("--no-llm-review", action="store_true", help="Parse with LLM but skip LLM review pass")
    args = ap.parse_args()

    use_llm = None
    provider = None
    if args.llm == "off":
        use_llm = False
    elif args.llm == "auto":
        use_llm = True  # resolve_provider decides
        provider = None
    else:
        use_llm = True
        provider = args.llm

    pub, report = audit_file(
        args.path,
        research_goal_level=args.goal,
        discipline=args.discipline,
        use_llm_parse=use_llm,
        use_llm_review=(False if args.no_llm_review else use_llm),
        llm_provider=provider,
    )
    errs = validate("report", report)
    out = args.out or Path(str(args.path) + ".audit-report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("source:", args.path)
    print("goal:", report["research_goal_level"], report["research_goal_level_source"])
    print("boundary:", report["boundary_note"][:200])
    print("verdict:", report["summary"]["verdict"], "|", report["summary"]["one_liner"])
    print("findings:", len(report["findings"]),
          "confirmed", report["summary"]["confirmed_count"],
          "needs_info", report["summary"]["needs_info_count"],
          "suggestion", report["summary"]["suggestion_count"])
    for f in report["findings"]:
        print(f"  - {f['id']} [{f['category']}/{f['severity']}] {f['title']}")
    print("questions:", len(report["clarifying_questions"]))
    print("CE rows:", len(report["claim_evidence_map"]["rows"]))
    for r in report["claim_evidence_map"]["rows"]:
        print(f"  - {r.get('id')} supports={r.get('design_supports')} | {r.get('claim')[:80]}")
    print("Plan A notes:", len(report["optimizer"]["change_notes"]))
    for n in report["optimizer"]["change_notes"]:
        print(f"  - {n['id']}: {n['summary'][:100]}")
    print("wrote:", out)
    if errs:
        print("SCHEMA ERRORS:")
        for e in errs:
            print(" ", e)
        return 1
    print("schema: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
