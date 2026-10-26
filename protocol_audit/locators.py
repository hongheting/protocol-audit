"""SourceLocator helpers."""
from __future__ import annotations

from typing import Any

_MEDIA_ALIASES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "txt": "text/plain",
    "text": "text/plain",
}


def normalize_media_type(media_type: str | None) -> str | None:
    if media_type is None:
        return None
    mt = media_type.strip()
    return _MEDIA_ALIASES.get(mt.lower(), mt)


def make_locator(
    source_file: str,
    original_text: str,
    *,
    media_type: str | None = None,
    page_number: int | None = None,
    paragraph_id: str | None = None,
    table_id: str | None = None,
    section_path: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> dict[str, Any]:
    loc: dict[str, Any] = {
        "source_file": source_file or "unknown",
        "original_text": (original_text or "")[:500],
    }
    mt = normalize_media_type(media_type)
    if mt is not None:
        loc["media_type"] = mt
    if page_number is not None:
        loc["page_number"] = page_number
    if paragraph_id is not None:
        loc["paragraph_id"] = paragraph_id
    if table_id is not None:
        loc["table_id"] = table_id
    if section_path is not None:
        loc["section_path"] = section_path
    if char_start is not None:
        loc["char_start"] = char_start
    if char_end is not None:
        loc["char_end"] = char_end
    return loc


def locator_from_block(block: dict[str, Any], source_file: str, media_type: str | None) -> dict[str, Any]:
    return make_locator(
        source_file,
        block.get("text") or "",
        media_type=media_type,
        page_number=block.get("page_number"),
        paragraph_id=block.get("paragraph_id"),
        table_id=block.get("table_id"),
        section_path=block.get("section_path"),
    )


def fallback_locator(source_file: str, media_type: str | None, snippet: str = "（全文未定位到精确段落，见方案原文）") -> dict[str, Any]:
    return make_locator(source_file, snippet, media_type=media_type)
