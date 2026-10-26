"""End-to-end pipeline: ingest → preview → confirm → audit report (+ optional LLM)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .design import apply_design_override
from .ingest import ingest_bytes, ingest_path
from .llm_client import resolve_provider
from .llm_parse import LLMParseError, llm_extract_design, merge_llm_into_design
from .preview import build_preview, public_preview
from .report import assemble_report


def build_parse_preview(
    *,
    path: Path | str | None = None,
    data: bytes | None = None,
    filename: str | None = None,
    media_type: str | None = None,
    protocol_text: str | None = None,
    research_goal_level: str | None = "unspecified",
    manual_supplements: list[dict[str, Any]] | None = None,
    scanned_pdf_ocr: str = "off",
    use_llm_parse: bool | None = None,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    if path is not None:
        ingest = ingest_path(path, scanned_pdf_ocr=scanned_pdf_ocr)
    elif data is not None:
        ingest = ingest_bytes(
            data,
            filename or "upload.bin",
            media_type=media_type,
            scanned_pdf_ocr=scanned_pdf_ocr,
        )
    elif protocol_text is not None:
        raw = protocol_text.encode("utf-8")
        ingest = ingest_bytes(
            raw,
            filename or "pasted.md",
            media_type=media_type or "text/markdown",
            scanned_pdf_ocr=scanned_pdf_ocr,
        )
    else:
        raise ValueError("Provide path, data, or protocol_text")

    preview = build_preview(
        ingest,
        user_goal_level=research_goal_level,
        manual_supplements=manual_supplements,
        user_confirmed=False,
    )

    # Optional LLM enrichment of design (default on if key present unless PROTOCOL_AUDIT_LLM=off)
    if use_llm_parse is None:
        use_llm_parse = resolve_provider(llm_provider) != "off" and os.environ.get("PROTOCOL_AUDIT_LLM", "auto") != "off"
        # Default for tests: keep off unless explicitly enabled
        if os.environ.get("PROTOCOL_AUDIT_LLM") is None and os.environ.get("RUN_LLM_TESTS") != "1":
            # In normal pytest / default CLI without flag: heuristic only
            use_llm_parse = False

    llm_meta = {"provider": "off", "ok": False, "skipped": True}
    if use_llm_parse:
        blocks = preview.get("ingested_blocks") or []
        source_file = preview.get("source_file") or "unknown"
        media = preview.get("media_type")
        # Real LLM mode: never silently succeed via heuristic after parse failure.
        # allow_heuristic_fallback stays False (V0.1.2.1 reliability).
        out = llm_extract_design(
            blocks,
            source_file=source_file,
            media_type=media,
            provider=llm_provider,
            allow_heuristic_fallback=False,
        )
        llm_meta = out.get("llm_meta") or llm_meta
        extract = out.get("design_extract")
        if llm_meta.get("hard_fail") or (not extract and resolve_provider(llm_provider) != "off"):
            err = (llm_meta.get("error") or "LLM design extract failed")
            preview["_llm_meta"] = llm_meta
            raise LLMParseError(err, llm_meta=llm_meta)
        design = preview.get("_design_full") or preview.get("extracted_design") or {}
        design = merge_llm_into_design(design, extract)
        design["_llm_meta"] = llm_meta
        preview["_design_full"] = design
        preview["extracted_design"] = {k: v for k, v in design.items() if not k.startswith("_")}
        preview["_llm_meta"] = llm_meta

    return preview


def run_audit(
    preview: dict[str, Any],
    *,
    confirm_design: bool = True,
    design_override: dict[str, Any] | None = None,
    research_goal_level: str | None = None,
    discipline: str = "auto",
    confirmation_notes: str = "",
    use_llm_review: bool | None = None,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    """Run real pipeline on preview. Does not return hardcoded fixture reports."""
    if not confirm_design:
        raise ValueError("confirm_design must be true to run full audit")

    design = preview.get("_design_full") or preview.get("extracted_design") or {}
    if research_goal_level is not None:
        design = dict(design)
        design["research_goal_level"] = research_goal_level
        if research_goal_level == "unspecified" and not (design_override or {}).get("research_goal_level"):
            design["research_goal_level_source"] = design.get("research_goal_level_source") or "default"
        else:
            design["research_goal_level_source"] = "user"
    design = apply_design_override(design, design_override)

    if "_hits" not in design and "_design_full" in preview:
        design["_hits"] = preview["_design_full"].get("_hits") or {}
    if "_llm_meta" not in design and preview.get("_llm_meta"):
        design["_llm_meta"] = preview["_llm_meta"]

    full_text = preview.get("_full_text") or "\n\n".join(
        b.get("text") or "" for b in (preview.get("ingested_blocks") or [])
    )
    source_file = preview.get("source_file") or "unknown"
    media_type = preview.get("media_type")

    confirmed_preview = dict(preview)
    confirmed_preview["user_confirmed"] = True
    if not confirmed_preview.get("confirmed_at"):
        from .preview import _now_iso
        confirmed_preview["confirmed_at"] = _now_iso()

    if use_llm_review is None:
        # Enable review when LLM parse was used or RUN_LLM_TESTS / PROTOCOL_AUDIT_LLM_REVIEW
        use_llm_review = bool(design.get("_llm_extract")) or os.environ.get("PROTOCOL_AUDIT_LLM_REVIEW") == "1"

    report = assemble_report(
        design=design,
        preview=confirmed_preview,
        source_file=source_file,
        media_type=media_type,
        full_text=full_text,
        discipline=discipline,
        confirmed=True,
        confirmed_at=confirmed_preview.get("confirmed_at"),
        confirmation_notes=confirmation_notes or (
            design_override.get("user_edits_summary", "") if design_override else confirmation_notes
        ),
        use_llm_review=bool(use_llm_review),
        llm_provider=llm_provider,
    )
    return report


def audit_file(
    path: Path | str,
    *,
    research_goal_level: str = "unspecified",
    discipline: str = "auto",
    manual_supplements: list[dict[str, Any]] | None = None,
    design_override: dict[str, Any] | None = None,
    use_llm_parse: bool | None = None,
    use_llm_review: bool | None = None,
    llm_provider: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience: preview + confirmed audit in one call (for CLI/tests)."""
    preview = build_parse_preview(
        path=path,
        research_goal_level=research_goal_level,
        manual_supplements=manual_supplements,
        use_llm_parse=use_llm_parse,
        llm_provider=llm_provider,
    )
    report = run_audit(
        preview,
        confirm_design=True,
        design_override=design_override,
        research_goal_level=research_goal_level,
        discipline=discipline,
        use_llm_review=use_llm_review,
        llm_provider=llm_provider,
    )
    return public_preview(preview), report
