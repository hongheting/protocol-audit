"""Review input window strategy (technical; not scientific Prompt).

V0.1.3.2: methods-first extraction + multi-window packing for long protocols.
Does not alter scientific review Prompt text/hash.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

# Same per-window budget as legacy full_text[:14000]
DEFAULT_WINDOW_CHARS = 14000
DEFAULT_MAX_WINDOWS = 3
TECH_VERSION = "0.1.3.2-review-windows"

# Heading-like lines (generic CN/EN; no trial-specific names)
_HEADING_START = re.compile(
    r"(?im)^[\s]*(?:"
    r"#{1,6}[\s]*|"                                  # markdown
    r"第[一二三四五六七八九十百零\d]+[章节部篇][\s\.、:：]*|"
    r"\d+(?:\.\d+)*[\.、\s]+|"
    r"[（(][一二三四五六七八九十\d]+[）)]\s*|"
    r"[一二三四五六七八九十]+[、\.\s]+"
    r")?"
    r"(?:"
    r"材料与方法|实验材料与方法|研究方法|实验方法|试验方法|"
    r"实验设计|试验设计|实验方案|研究方案|分组(?:与对照)?|对照(?:设置)?|"
    r"统计分析|统计方法|数据处理|采样(?:方案|方法)?|取样|"
    r"重复(?:与)?(?:随机化)?|随机化|"
    r"Materials?\s*(?:and|&)\s*Methods?|Methods?(?:\s+and\s+Materials?)?|"
    r"Experimental\s+Design|Study\s+Design|Statistical\s+Analysis|"
    r"Sampling|Replication|Controls?"
    r")"
    r"[^\n]{0,60}$"
)

# End of methods-ish section when a later major heading appears
_SECTION_END = re.compile(
    r"(?im)^[\s]*(?:"
    r"#{1,6}[\s]*|"
    r"第[四五六七八九十百零\d]+[章节部篇][\s\.、:：]*|"
    r"\d+(?:\.\d+)*[\.、\s]+|"
    r"[（(][四五六七八九十\d]+[）)]\s*"
    r")?"
    r"(?:"
    r"结果(?:与讨论)?|讨论|结论|展望|参考文献|致谢|附录|"
    r"Results?(?:\s+and\s+Discussion)?|Discussion|Conclusions?|"
    r"References|Acknowledgements?|Appendix|"
    r"背景|引言|文献综述|Introduction|Background|Literature\s+Review"
    r")"
    r"[^\n]{0,60}$"
)

_SIGNAL_KW = re.compile(
    r"(分组|对照|空白|载体|溶剂|重复|复孔|独立|随机|区组|采样|取样|"
    r"统计|ANOVA|方差|回归|混杂|伪重复|实验单位|处理组|"
    r"control|replicat|randomi[sz]|ANOVA|treat(ment)?\s*group|"
    r"blank|vehicle|solvent)",
    re.I,
)


@dataclass
class ReviewWindow:
    window_id: str
    start: int
    end: int
    text: str
    priority: int
    reason: str

    def meta(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "start": self.start,
            "end": self.end,
            "char_len": len(self.text),
            "priority": self.priority,
            "reason": self.reason,
            "text_sha16": _sha16(self.text),
            "preview": self.text[:240],
        }


@dataclass
class ReviewCoverage:
    tech_version: str = TECH_VERSION
    total_chars: int = 0
    chars_sent: int = 0
    window_count: int = 0
    window_budget_chars: int = DEFAULT_WINDOW_CHARS
    max_windows: int = DEFAULT_MAX_WINDOWS
    methods_detected: bool = False
    methods_included: bool = False
    methods_spans: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    omitted_char_count: int = 0
    omitted_ranges: list[dict[str, int]] = field(default_factory=list)
    comprehensive: bool = True
    notes: list[str] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_zh(self) -> str:
        parts = [
            f"review_coverage[{self.tech_version}]: "
            f"全文 {self.total_chars} 字，送审 {self.chars_sent} 字/"
            f"{self.window_count} 窗（单窗上限 {self.window_budget_chars}）"
        ]
        if self.methods_detected:
            parts.append("方法段已检出且" + ("已入窗" if self.methods_included else "未入窗"))
        else:
            parts.append("未检出明确方法标题段（已用信号段落兜底）" if self.methods_included else "未检出方法段")
        if self.truncated:
            parts.append(f"存在截断/遗漏约 {self.omitted_char_count} 字")
        if self.comprehensive:
            parts.append("可声称覆盖本次送审窗口（非未解析资产）")
        else:
            parts.append("不得声称全面审查")
        if self.notes:
            parts.append("；".join(self.notes[:4]))
        return "。".join(parts) + "。"


def _sha16(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def detect_methods_spans(full_text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, label) spans for methods/design sections."""
    spans: list[tuple[int, int, str]] = []
    starts: list[tuple[int, str]] = []
    for m in _HEADING_START.finditer(full_text):
        label = m.group(0).strip()[:80]
        starts.append((m.start(), label))
    if not starts:
        return []

    # Deduplicate starts within 40 chars
    compact: list[tuple[int, str]] = []
    for pos, lab in starts:
        if compact and pos - compact[-1][0] < 40:
            continue
        compact.append((pos, lab))

    for i, (pos, lab) in enumerate(compact):
        # default end: next heading start of any major type, or +8000
        next_bound = len(full_text)
        if i + 1 < len(compact):
            next_bound = compact[i + 1][0]
        # also stop at Results/Discussion etc. after this start
        end_m = _SECTION_END.search(full_text, pos + 1)
        end = next_bound
        if end_m and end_m.start() < end and end_m.start() > pos + 80:
            # only if it looks like leaving methods
            end = end_m.start()
        # clamp span length
        end = min(end, pos + 12000, len(full_text))
        if end - pos < 12:
            continue
        spans.append((pos, end, lab))

    # Merge overlapping
    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for s, e, lab in spans:
        if merged and s <= merged[-1][1] + 20:
            ps, pe, pl = merged[-1]
            merged[-1] = (ps, max(pe, e), pl if len(pl) >= len(lab) else lab)
        else:
            merged.append((s, e, lab))
    return merged


def _signal_segments(full_text: str, min_hits: int = 2) -> list[tuple[int, int]]:
    """Paragraph-ish segments with design-signal keywords."""
    segs: list[tuple[int, int, int]] = []
    # split on blank lines while tracking offsets
    parts = re.split(r"(\n\s*\n)", full_text)
    offset = 0
    buf = ""
    buf_start = 0
    for part in parts:
        if re.fullmatch(r"\n\s*\n", part or ""):
            if buf.strip():
                hits = len(_SIGNAL_KW.findall(buf))
                if hits >= min_hits:
                    segs.append((buf_start, buf_start + len(buf), hits))
            offset += len(part)
            buf = ""
            buf_start = offset
            continue
        if not buf:
            buf_start = offset
        buf += part
        offset += len(part)
    if buf.strip():
        hits = len(_SIGNAL_KW.findall(buf))
        if hits >= min_hits:
            segs.append((buf_start, buf_start + len(buf), hits))
    segs.sort(key=lambda x: (-x[2], x[0]))
    return [(s, e) for s, e, _ in segs]


def _pack_ranges(ranges: list[tuple[int, int]], full_text: str, budget: int) -> tuple[str, list[tuple[int, int]]]:
    """Pack non-overlapping ranges into a budgeted string with markers."""
    selected: list[tuple[int, int]] = []
    used = 0
    for s, e in ranges:
        if e <= s:
            continue
        # skip fully covered
        if any(s >= a and e <= b for a, b in selected):
            continue
        chunk_len = e - s
        overhead = 48  # marker
        if used + chunk_len + overhead > budget and selected:
            # try partial fill
            remain = budget - used - overhead
            if remain > 400:
                selected.append((s, s + remain))
                used += remain + overhead
            break
        if used + chunk_len + overhead > budget and not selected:
            selected.append((s, min(e, s + budget - overhead)))
            used = budget
            break
        selected.append((s, e))
        used += chunk_len + overhead
    selected.sort()
    parts = []
    for s, e in selected:
        parts.append(f"【原文定位 {s}:{e}】\n{full_text[s:e]}")
    return "\n\n".join(parts), selected


def _uncovered_ranges(total: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if total <= 0:
        return []
    cov = sorted(covered)
    merged: list[tuple[int, int]] = []
    for s, e in cov:
        s = max(0, s)
        e = min(total, e)
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out: list[tuple[int, int]] = []
    cur = 0
    for s, e in merged:
        if cur < s:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < total:
        out.append((cur, total))
    return out


def build_review_windows(
    full_text: str,
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    max_windows: int = DEFAULT_MAX_WINDOWS,
) -> tuple[list[ReviewWindow], ReviewCoverage]:
    """Build methods-first review windows and coverage metadata."""
    text = full_text or ""
    n = len(text)
    cov = ReviewCoverage(
        total_chars=n,
        window_budget_chars=window_chars,
        max_windows=max_windows,
    )

    if n == 0:
        cov.comprehensive = False
        cov.notes.append("原文为空")
        return [], cov

    if n <= window_chars:
        w = ReviewWindow(
            window_id="W01",
            start=0,
            end=n,
            text=text,
            priority=0,
            reason="短文全文入窗（未截断）",
        )
        cov.window_count = 1
        cov.chars_sent = n
        cov.comprehensive = True
        cov.truncated = False
        methods = detect_methods_spans(text)
        cov.methods_detected = bool(methods)
        cov.methods_included = True  # entire text included
        cov.methods_spans = [{"start": s, "end": e, "label": lab} for s, e, lab in methods]
        cov.windows = [w.meta()]
        cov.notes.append("短文不截断")
        return [w], cov

    methods = detect_methods_spans(text)
    cov.methods_detected = bool(methods)
    cov.methods_spans = [{"start": s, "end": e, "label": lab} for s, e, lab in methods]

    # Priority pack for W01: methods spans first, then signal segments, then head
    priority_ranges: list[tuple[int, int]] = [(s, e) for s, e, _ in methods]
    for s, e in _signal_segments(text):
        priority_ranges.append((s, e))
    # always prefer document head for hypotheses/claims context
    priority_ranges.append((0, min(3500, n)))

    # de-dup order-preserving
    seen_ranges: list[tuple[int, int]] = []
    ordered: list[tuple[int, int]] = []
    for s, e in priority_ranges:
        key = (s, e)
        if key in seen_ranges:
            continue
        seen_ranges.append(key)
        ordered.append((s, e))

    w1_text, w1_cov = _pack_ranges(ordered, text, window_chars)
    windows: list[ReviewWindow] = [
        ReviewWindow(
            window_id="W01",
            start=w1_cov[0][0] if w1_cov else 0,
            end=w1_cov[-1][1] if w1_cov else 0,
            text=w1_text,
            priority=0,
            reason="方法优先+设计信号打包",
        )
    ]
    covered = list(w1_cov)
    methods_chars = sum(e - s for s, e, _ in methods)
    methods_in = 0
    for ms, me, _ in methods:
        for cs, ce in covered:
            methods_in += max(0, min(me, ce) - max(ms, cs))
    cov.methods_included = (not methods) or (methods_in >= max(80, int(0.5 * methods_chars)))

    # Fill remaining windows with sequential uncovered chunks (large first)
    omitted = _uncovered_ranges(n, covered)
    wi = 2
    while omitted and len(windows) < max_windows:
        # take the largest omitted range
        omitted.sort(key=lambda x: -(x[1] - x[0]))
        s, e = omitted[0]
        take = min(e, s + window_chars)
        chunk = text[s:take]
        marked = f"【原文定位 {s}:{take}】\n{chunk}"
        windows.append(
            ReviewWindow(
                window_id=f"W{wi:02d}",
                start=s,
                end=take,
                text=marked if len(marked) <= window_chars + 64 else marked[: window_chars + 64],
                priority=wi - 1,
                reason="长文续窗（遗漏区间）",
            )
        )
        covered.append((s, take))
        omitted = _uncovered_ranges(n, covered)
        wi += 1

    # coverage stats: approximate unique covered chars
    uniq = 0
    cur_cov = sorted(covered)
    merged_c: list[tuple[int, int]] = []
    for s, e in cur_cov:
        if merged_c and s <= merged_c[-1][1]:
            merged_c[-1] = (merged_c[-1][0], max(merged_c[-1][1], e))
        else:
            merged_c.append((s, e))
    for s, e in merged_c:
        uniq += e - s

    cov.window_count = len(windows)
    cov.chars_sent = sum(len(w.text) for w in windows)
    cov.omitted_ranges = [{"start": s, "end": e} for s, e in _uncovered_ranges(n, merged_c)]
    cov.omitted_char_count = sum(e - s for s, e in _uncovered_ranges(n, merged_c))
    cov.truncated = cov.omitted_char_count > 0
    cov.windows = [w.meta() for w in windows]

    if not cov.methods_detected:
        cov.notes.append("未匹配到方法/设计标题，已用关键词信号段兜底")
    elif not cov.methods_included:
        cov.notes.append("方法段未能充分进入送审窗口")
    if cov.truncated:
        cov.notes.append(f"仍有 {cov.omitted_char_count} 字未送审")

    # comprehensive only if methods (when detected) included AND omit small or none
    # For long docs, multi-window still may omit — never claim full review if omit > 5%
    omit_ratio = cov.omitted_char_count / max(1, n)
    cov.comprehensive = (
        (cov.methods_included if cov.methods_detected else True)
        and omit_ratio <= 0.05
        and cov.window_count >= 1
    )
    if not cov.comprehensive:
        cov.notes.append("审查输入非全文覆盖，禁止声称全面审查")

    return windows, cov
