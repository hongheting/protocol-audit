"""Ingest Word / PDF / text into anchored blocks."""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


def media_type_for(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    return MEDIA.get(suffix, "text/plain")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_bytes(
    data: bytes,
    filename: str,
    *,
    media_type: str | None = None,
    scanned_pdf_ocr: str = "off",
) -> dict[str, Any]:
    """Return ingest result: blocks, warnings, unparsed_assets, tables_count, full_text."""
    path_hint = Path(filename)
    mt = media_type or media_type_for(path_hint)
    suffix = path_hint.suffix.lower()
    if mt.endswith("wordprocessingml.document") or suffix == ".docx":
        return _ingest_docx(data, filename, mt)
    if mt == "application/pdf" or suffix == ".pdf":
        return _ingest_pdf(data, filename, mt, scanned_pdf_ocr=scanned_pdf_ocr)
    text = data.decode("utf-8", errors="replace")
    return _ingest_text(text, filename, mt)


def ingest_path(path: Path | str, **kwargs: Any) -> dict[str, Any]:
    p = Path(path)
    return ingest_bytes(p.read_bytes(), p.name, media_type=media_type_for(p), **kwargs)


def _ingest_text(text: str, filename: str, media_type: str) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    warnings: list[str] = []
    # Split markdown tables vs paragraphs
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    para_buf: list[str] = []
    para_idx = 0
    table_idx = 0

    def flush_para():
        nonlocal para_idx
        raw = "\n".join(para_buf).strip()
        para_buf.clear()
        if not raw:
            return
        para_idx += 1
        pid = f"p-{para_idx}"
        btype = "heading" if re.match(r"^#{1,6}\s+\S", raw) or (
            len(raw) < 80 and not raw.endswith("。") and not raw.endswith(".")
            and re.match(r"^[\d一二三四五六七八九十]+[\.、．]\s*\S", raw)
        ) else "paragraph"
        blocks.append({
            "block_id": pid,
            "block_type": btype,
            "text": raw,
            "page_number": None,
            "paragraph_id": pid,
            "table_id": None,
            "section_path": None,
            "source": "extracted",
        })

    while i < len(lines):
        line = lines[i]
        if _looks_like_md_table_row(line) and i + 1 < len(lines) and _looks_like_md_separator(lines[i + 1]):
            flush_para()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and _looks_like_md_table_row(lines[i]):
                table_lines.append(lines[i])
                i += 1
            table_idx += 1
            tid = f"t-{table_idx}"
            blocks.append({
                "block_id": tid,
                "block_type": "table",
                "text": "\n".join(table_lines),
                "page_number": None,
                "paragraph_id": None,
                "table_id": tid,
                "section_path": None,
                "source": "extracted",
            })
            continue
        if line.strip() == "":
            flush_para()
        else:
            para_buf.append(line)
        i += 1
    flush_para()

    if not blocks:
        warnings.append("文本为空或无法分块")
        blocks.append({
            "block_id": "p-1",
            "block_type": "paragraph",
            "text": text or "",
            "page_number": None,
            "paragraph_id": "p-1",
            "table_id": None,
            "section_path": None,
            "source": "extracted",
        })

    tables_count = sum(1 for b in blocks if b["block_type"] == "table")
    return {
        "source_file": filename,
        "media_type": media_type,
        "blocks": blocks,
        "parse_warnings": warnings,
        "unparsed_assets": [],
        "tables_count": tables_count,
        "full_text": "\n\n".join(b["text"] for b in blocks),
        "byte_size": len(text.encode("utf-8")),
        "sha256": sha256_bytes(text.encode("utf-8")),
    }


def _looks_like_md_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _looks_like_md_separator(line: str) -> bool:
    s = line.strip()
    if not (s.startswith("|") and "-" in s):
        return False
    return bool(re.match(r"^\|[\s\-:|]+\|$", s))


def _ingest_docx(data: bytes, filename: str, media_type: str) -> dict[str, Any]:
    from docx import Document
    from docx.oxml.ns import qn

    warnings: list[str] = []
    unparsed: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    para_idx = 0
    table_idx = 0
    img_idx = 0

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        doc = Document(str(tmp_path))
        # Walk body in order: paragraphs and tables are siblings in body
        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag
            if tag == qn("w:p"):
                # find corresponding paragraph
                texts = [node.text for node in child.iter(qn("w:t")) if node.text]
                text = "".join(texts).strip()
                # images in paragraph
                drawings = list(child.iter(qn("w:drawing")))
                if drawings:
                    img_idx += 1
                    unparsed.append({
                        "id": f"U-img-{img_idx}",
                        "asset_type": "image",
                        "reason": "嵌入图片/绘图对象，V0.1 不解析位图内容",
                        "page_number": None,
                        "section_path": None,
                        "caption_hint": text[:80] if text else None,
                    })
                if not text:
                    continue
                para_idx += 1
                pid = f"p-{para_idx}"
                style = ""
                # crude heading detect via pStyle
                pPr = child.find(qn("w:pPr"))
                if pPr is not None:
                    pStyle = pPr.find(qn("w:pStyle"))
                    if pStyle is not None:
                        style = pStyle.get(qn("w:val")) or ""
                btype = "heading" if style.lower().startswith("heading") or style.startswith("标题") else "paragraph"
                blocks.append({
                    "block_id": pid,
                    "block_type": btype,
                    "text": text,
                    "page_number": None,
                    "paragraph_id": pid,
                    "table_id": None,
                    "section_path": None,
                    "source": "extracted",
                })
            elif tag == qn("w:tbl"):
                table_idx += 1
                tid = f"t-{table_idx}"
                rows_text: list[str] = []
                for tr in child.iter(qn("w:tr")):
                    cells: list[str] = []
                    for tc in tr.iter(qn("w:tc")):
                        cell_texts = [n.text for n in tc.iter(qn("w:t")) if n.text]
                        cells.append("".join(cell_texts).strip())
                    # each cell appears nested; take unique consecutive? simpler: collect direct tc children
                    # Reset: get only direct row cells
                rows_text = []
                for tr in child.findall(qn("w:tr")):
                    cells = []
                    for tc in tr.findall(qn("w:tc")):
                        cell_texts = [n.text for n in tc.iter(qn("w:t")) if n.text]
                        cells.append("".join(cell_texts).strip())
                    rows_text.append(" | ".join(cells))
                table_text = "\n".join(rows_text)
                blocks.append({
                    "block_id": tid,
                    "block_type": "table",
                    "text": table_text,
                    "page_number": None,
                    "paragraph_id": None,
                    "table_id": tid,
                    "section_path": None,
                    "source": "extracted",
                })
    finally:
        tmp_path.unlink(missing_ok=True)

    if not blocks:
        warnings.append("Word 文档未提取到段落或表格；请粘贴文本或检查文件")
        blocks.append({
            "block_id": "p-1",
            "block_type": "paragraph",
            "text": "",
            "page_number": None,
            "paragraph_id": "p-1",
            "table_id": None,
            "section_path": None,
            "source": "extracted",
        })

    return {
        "source_file": filename,
        "media_type": media_type,
        "blocks": blocks,
        "parse_warnings": warnings,
        "unparsed_assets": unparsed,
        "tables_count": sum(1 for b in blocks if b["block_type"] == "table"),
        "full_text": "\n\n".join(b["text"] for b in blocks),
        "byte_size": len(data),
        "sha256": sha256_bytes(data),
    }


def _ingest_pdf(
    data: bytes,
    filename: str,
    media_type: str,
    *,
    scanned_pdf_ocr: str = "off",
) -> dict[str, Any]:
    warnings: list[str] = []
    unparsed: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    page_texts: list[str] = []
    try:
        # Prefer pdftotext -layout - for page breaks use -f/-l loop or formfeed
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(tmp_path), "-"],
                capture_output=True,
                check=False,
            )
            raw = proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""
        except FileNotFoundError:
            raw = ""
            warnings.append("系统未找到 pdftotext，改用 pypdf")

        if not raw.strip():
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(tmp_path))
                for i, page in enumerate(reader.pages, start=1):
                    t = page.extract_text() or ""
                    page_texts.append(t)
                raw = "\n\n".join(page_texts)
            except Exception as e:
                warnings.append(f"PDF 文本提取失败：{e}")
                raw = ""
        else:
            # pdftotext with form feeds between pages if -layout; split by \f
            if "\f" in raw:
                page_texts = raw.split("\f")
            else:
                # estimate pages via pdfinfo or pypdf
                try:
                    from pypdf import PdfReader
                    n = len(PdfReader(str(tmp_path)).pages)
                except Exception:
                    n = 1
                if n <= 1:
                    page_texts = [raw]
                else:
                    # single blob — put all on page 1 with warning
                    page_texts = [raw]
                    warnings.append("未能可靠分页，全部文本暂记为第 1 页锚点")

        total_chars = sum(len(t.strip()) for t in page_texts)
        if total_chars < 40:
            warnings.append(
                "检测到扫描型或无文本层 PDF：无法提取正文/表格。"
                "请手动粘贴关键表格与分组信息（来源将标记为 manual_input）。"
                "V0.1 不强制 OCR。"
            )
            unparsed.append({
                "id": "U-scanned-table-1",
                "asset_type": "scanned_table",
                "reason": "扫描 PDF / 无文本层，表格未能抽取（OCR 为 P1，V0.1 不强制）",
                "page_number": 1,
                "section_path": None,
                "caption_hint": None,
            })
            blocks.append({
                "block_id": "p-1",
                "block_type": "paragraph",
                "text": raw.strip() or "（扫描 PDF：无可用文本层）",
                "page_number": 1,
                "paragraph_id": "p-1",
                "table_id": None,
                "section_path": None,
                "source": "extracted",
            })
        else:
            para_idx = 0
            table_idx = 0
            for page_no, page_text in enumerate(page_texts, start=1):
                page_text = page_text.strip()
                if not page_text:
                    continue
                # Heuristic table: lines with many spaces / tabs aligning as columns
                for chunk in re.split(r"\n\s*\n", page_text):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    lines = chunk.split("\n")
                    if _looks_like_text_table(lines):
                        table_idx += 1
                        tid = f"t-{table_idx}"
                        blocks.append({
                            "block_id": tid,
                            "block_type": "table",
                            "text": chunk,
                            "page_number": page_no,
                            "paragraph_id": None,
                            "table_id": tid,
                            "section_path": None,
                            "source": "extracted",
                        })
                    else:
                        para_idx += 1
                        pid = f"p-{para_idx}"
                        blocks.append({
                            "block_id": pid,
                            "block_type": "paragraph",
                            "text": chunk,
                            "page_number": page_no,
                            "paragraph_id": pid,
                            "table_id": None,
                            "section_path": None,
                            "source": "extracted",
                        })
            if table_idx == 0 and any("表" in b["text"][:20] or "Table" in b["text"][:20] for b in blocks):
                warnings.append(
                    "PDF 中疑似提到表格，但未能可靠解析为结构化表。"
                    "若关键分组信息在表中，请手动粘贴补充。"
                )
    finally:
        tmp_path.unlink(missing_ok=True)

    _ = scanned_pdf_ocr  # P1 reserved; V0.1 default off

    return {
        "source_file": filename,
        "media_type": media_type,
        "blocks": blocks,
        "parse_warnings": warnings,
        "unparsed_assets": unparsed,
        "tables_count": sum(1 for b in blocks if b["block_type"] == "table"),
        "full_text": "\n\n".join(b["text"] for b in blocks),
        "byte_size": len(data),
        "sha256": sha256_bytes(data),
    }


def _looks_like_text_table(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    pipeish = sum(1 for ln in lines if ln.count("|") >= 2)
    if pipeish >= 2:
        return True
    # multiple lines with 2+ big gaps
    spaced = sum(1 for ln in lines if re.search(r"\S\s{2,}\S.*\s{2,}\S", ln))
    return spaced >= 2
