"""Build ParsePreview from ingest + design."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from .design import extract_design

TZ = timezone(timedelta(hours=8))


def build_preview(
    ingest: dict[str, Any],
    *,
    user_goal_level: str | None = None,
    manual_supplements: list[dict[str, Any]] | None = None,
    user_confirmed: bool = False,
    user_edits_summary: str | None = None,
) -> dict[str, Any]:
    blocks = list(ingest.get("blocks") or [])
    supplements = list(manual_supplements or [])
    unparsed = list(ingest.get("unparsed_assets") or [])
    warnings = list(ingest.get("parse_warnings") or [])

    # Merge manual tables/text into blocks
    for i, sup in enumerate(supplements, start=1):
        sid = sup.get("id") or f"manual-{i}"
        text = sup.get("text") or ""
        kind = sup.get("kind") or "table"
        block = {
            "block_id": sid,
            "block_type": "table" if kind == "table" else "paragraph",
            "text": text,
            "page_number": None,
            "paragraph_id": None if kind == "table" else sid,
            "table_id": sid if kind == "table" else None,
            "section_path": None,
            "source": "manual_input",
        }
        blocks.append(block)
        # remove replaced unparsed asset
        rid = sup.get("replaces_unparsed_asset_id")
        if rid:
            unparsed = [u for u in unparsed if u.get("id") != rid]

    tables_count = sum(1 for b in blocks if b.get("block_type") == "table")
    full_text = "\n\n".join(b.get("text") or "" for b in blocks)

    design = extract_design(
        blocks,
        source_file=ingest.get("source_file") or "unknown",
        media_type=ingest.get("media_type"),
        full_text=full_text,
        user_goal_level=user_goal_level,
    )

    # Strip internal hits from user-facing extracted_design copy? Keep for pipeline;
    # UI can ignore _hits. Schema allows additionalProperties on extracted_design.
    limited = _limited_audit_recommended(design, warnings, unparsed, tables_count)

    if any("扫描" in w or "无文本层" in w for w in warnings) and not supplements:
        warnings = list(dict.fromkeys(warnings + [
            "扫描/无文本层表格未解析：请在下方手动粘贴分组表（将标记为 manual_input）。"
        ]))

    preview = {
        "schema_version": "0.2.0",
        "source_file": ingest.get("source_file") or "unknown",
        "media_type": ingest.get("media_type"),
        "ingested_blocks": [
            {k: v for k, v in b.items() if k in (
                "block_id", "block_type", "text", "page_number",
                "paragraph_id", "table_id", "section_path", "source",
            )}
            for b in blocks
        ],
        "extracted_design": {k: v for k, v in design.items() if not k.startswith("_")},
        "unparsed_assets": unparsed,
        "parse_warnings": warnings,
        "tables_parsed_count": tables_count,
        "user_confirmed": user_confirmed,
        "user_edits_summary": user_edits_summary or "",
        "confirmed_at": _now_iso() if user_confirmed else None,
        "manual_supplements": [
            {
                "id": s.get("id") or f"manual-{i}",
                "kind": s.get("kind") or "table",
                "text": s.get("text") or "",
                "source": "manual_input",
                "replaces_unparsed_asset_id": s.get("replaces_unparsed_asset_id"),
            }
            for i, s in enumerate(supplements, start=1)
        ],
        "limited_audit_recommended": limited,
        # internal for pipeline (not in schema — strip before validate if needed)
        "_design_full": design,
        "_full_text": full_text,
        "_ingest_meta": {
            "byte_size": ingest.get("byte_size"),
            "sha256": ingest.get("sha256"),
        },
    }
    return preview


def public_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Drop internal keys for schema validation / API response."""
    return {k: v for k, v in preview.items() if not k.startswith("_")}


def _limited_audit_recommended(
    design: dict[str, Any],
    warnings: list[str],
    unparsed: list[dict[str, Any]],
    tables_count: int,
) -> bool:
    if any(u.get("asset_type") == "scanned_table" for u in unparsed):
        return True
    if any("扫描" in w or "无文本层" in w for w in warnings) and tables_count == 0:
        return True
    groups = design.get("groups") or []
    if not groups:
        return True
    rep = design.get("replication") or {}
    if not rep.get("text") and not groups:
        return True
    return False


def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")
