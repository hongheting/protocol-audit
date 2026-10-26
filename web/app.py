"""ProtocolAudit V0.1.3.3 Beta — Flask UI (upload → preview → confirm → report).

Beta hardening (release blockers only):
- upload extension allowlist + size cap
- in-memory rate limit
- API keys never exposed to client (LLM keys stay in protocol_audit.llm_client)
- require strong secret when PROTOCOL_AUDIT_ENV=production
- Basic auth (refcheck-style demo + password secret); production requires password
- /health exempt from Basic auth (Container Apps probes)
- user-facing errors without traceback
- job id entropy + optional TTL retention for unpublished protocols
- surface review completeness via boundary_note / finding.origin in report template
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from protocol_audit.pipeline import build_parse_preview, run_audit  # noqa: E402
from protocol_audit.preview import public_preview  # noqa: E402
from protocol_audit.schema_validate import validate  # noqa: E402

BASE = Path(__file__).resolve().parent
JOBS = BASE / "jobs"
JOBS.mkdir(exist_ok=True)

ALLOWED_SUFFIXES = {".docx", ".pdf", ".md", ".markdown", ".txt"}
MAX_UPLOAD_BYTES = int(os.environ.get("PROTOCOL_AUDIT_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
RATE_LIMIT_WINDOW_S = int(os.environ.get("PROTOCOL_AUDIT_RATE_WINDOW_S", "60"))
RATE_LIMIT_MAX = int(os.environ.get("PROTOCOL_AUDIT_RATE_MAX", "20"))
JOB_TTL_HOURS = float(os.environ.get("PROTOCOL_AUDIT_JOB_TTL_HOURS", "24"))
IS_PRODUCTION = os.environ.get("PROTOCOL_AUDIT_ENV", "").strip().lower() in ("production", "prod", "beta")

app = Flask(__name__)
_secret = os.environ.get("PROTOCOL_AUDIT_SECRET", "").strip()
if IS_PRODUCTION:
    if not _secret or _secret == "dev-skeleton-a":
        raise RuntimeError(
            "PROTOCOL_AUDIT_ENV=production requires PROTOCOL_AUDIT_SECRET "
            "(non-default) before starting the web app."
        )
    app.secret_key = _secret
else:
    app.secret_key = _secret or "dev-skeleton-a"
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# Basic auth (refcheck-style). User default "demo"; password via env or *_FILE.
# Aliases: PROTOCOL_AUDIT_DEMO_PASSWORD / PROTOCOL_AUDIT_BASIC_PASSWORD (+ _FILE).
def _read_password_file(path_env: str | None) -> str:
    if not path_env:
        return ""
    try:
        return Path(path_env).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_BASIC_USER = (
    os.environ.get("PROTOCOL_AUDIT_BASIC_USER")
    or os.environ.get("PROTOCOL_AUDIT_DEMO_USER")
    or "demo"
).strip() or "demo"
_DEMO_PW = (
    (os.environ.get("PROTOCOL_AUDIT_DEMO_PASSWORD") or "").strip()
    or (os.environ.get("PROTOCOL_AUDIT_BASIC_PASSWORD") or "").strip()
    or _read_password_file(os.environ.get("PROTOCOL_AUDIT_DEMO_PASSWORD_FILE"))
    or _read_password_file(os.environ.get("PROTOCOL_AUDIT_BASIC_PASSWORD_FILE"))
)
if IS_PRODUCTION and not _DEMO_PW:
    raise RuntimeError(
        "PROTOCOL_AUDIT_ENV=production requires PROTOCOL_AUDIT_DEMO_PASSWORD "
        "(or PROTOCOL_AUDIT_BASIC_PASSWORD / *_FILE) for controlled-beta Basic auth."
    )


@app.before_request
def _basic_auth():
    # ACA / K8s probes must not need credentials.
    if request.path == "/health" or request.path.startswith("/static/"):
        return None
    if not _DEMO_PW:
        return None  # non-production local/dev may skip Basic auth
    a = request.authorization
    user_ok = a and hmac.compare_digest((a.username or "").encode(), _BASIC_USER.encode())
    pass_ok = a and hmac.compare_digest((a.password or "").encode(), _DEMO_PW.encode())
    if user_ok and pass_ok:
        return None
    from flask import Response

    return Response("需要访问口令", 401, {"WWW-Authenticate": 'Basic realm="protocol-audit-beta"'})


# ip -> deque[timestamps]
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_ip() -> str:
    # Prefer first X-Forwarded-For hop when behind a trusted reverse proxy.
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return xff or (request.remote_addr or "unknown")


def _rate_limited(bucket: str) -> bool:
    """Return True if the caller exceeded the sliding-window budget."""
    key = f"{bucket}:{_client_ip()}"
    now = time.time()
    q = _rate_buckets[key]
    while q and now - q[0] > RATE_LIMIT_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_LIMIT_MAX:
        return True
    q.append(now)
    return False


def _safe_job_id(raw: str) -> str | None:
    """Accept only hex job ids we generate (32 hex chars from uuid4)."""
    if not raw or len(raw) > 64:
        return None
    try:
        bytes.fromhex(raw)
    except ValueError:
        return None
    return raw


def _job_dir(jid: str, *, create: bool = True) -> Path | None:
    safe = _safe_job_id(jid)
    if not safe:
        return None
    d = JOBS / safe
    if create:
        d.mkdir(parents=True, exist_ok=True)
    elif not d.is_dir():
        return None
    return d


def _cleanup_expired_jobs() -> int:
    """Delete job dirs older than JOB_TTL_HOURS. Best-effort; never raises to callers."""
    if JOB_TTL_HOURS <= 0:
        return 0
    cutoff = time.time() - JOB_TTL_HOURS * 3600
    removed = 0
    try:
        for child in JOBS.iterdir():
            if not child.is_dir():
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                # Remove files then dir
                try:
                    for f in child.iterdir():
                        try:
                            f.unlink()
                        except OSError:
                            pass
                    child.rmdir()
                    removed += 1
                except OSError:
                    pass
    except OSError:
        return removed
    return removed


def _allowed_upload(filename: str) -> bool:
    suf = Path(filename).suffix.lower()
    return suf in ALLOWED_SUFFIXES


@app.before_request
def _before():
    # Occasional cleanup (cheap) — every ~32nd request by time bucket
    if int(time.time()) % 32 == 0:
        _cleanup_expired_jobs()


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/upload")
def upload():
    if _rate_limited("upload"):
        flash("请求过于频繁，请稍后再试（访问限流）。")
        return redirect(url_for("index")), 429

    f = request.files.get("file")
    text = (request.form.get("protocol_text") or "").strip()
    goal = request.form.get("research_goal_level") or "unspecified"
    discipline = request.form.get("discipline") or "auto"

    jid = uuid.uuid4().hex  # 32 hex chars
    d = _job_dir(jid)
    assert d is not None

    try:
        if f and f.filename:
            filename = Path(f.filename).name  # strip any path components
            if not _allowed_upload(filename):
                flash(
                    "不支持的文件类型。请上传 Word(.docx)、PDF(.pdf) 或 Markdown/文本(.md/.txt)。"
                )
                return redirect(url_for("index"))
            data = f.read()
            if len(data) > MAX_UPLOAD_BYTES:
                flash(f"文件过大（上限 {MAX_UPLOAD_BYTES // (1024*1024)} MB）。")
                return redirect(url_for("index"))
            (d / "upload.bin").write_bytes(data)
            (d / "meta.json").write_text(
                json.dumps(
                    {
                        "filename": filename,
                        "goal": goal,
                        "discipline": discipline,
                        "created_at": time.time(),
                        "privacy_note": "unpublished protocol retained on server for JOB_TTL only; not sent to public literature search by default",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview = build_parse_preview(
                data=data,
                filename=filename,
                research_goal_level=goal,
            )
        elif len(text) >= 40:
            if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
                flash("粘贴文本过大。")
                return redirect(url_for("index"))
            (d / "meta.json").write_text(
                json.dumps(
                    {
                        "filename": "pasted.md",
                        "goal": goal,
                        "discipline": discipline,
                        "created_at": time.time(),
                        "privacy_note": "unpublished protocol retained on server for JOB_TTL only",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview = build_parse_preview(
                protocol_text=text,
                filename="pasted.md",
                research_goal_level=goal,
            )
        else:
            flash("请上传 Word/PDF/Markdown，或粘贴不少于 40 字的方案文本。")
            return redirect(url_for("index"))
    except Exception as e:  # noqa: BLE001 — user-facing; no traceback
        flash(f"解析失败：{type(e).__name__}: {e}")
        return redirect(url_for("index"))

    (d / "preview.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("preview", job_id=jid))


@app.get("/preview/<job_id>")
def preview(job_id: str):
    d = _job_dir(job_id, create=False)
    if d is None:
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    path = d / "preview.json"
    if not path.exists():
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    preview = json.loads(path.read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    pub = public_preview(preview)
    errs = validate("preview", pub)
    return render_template(
        "preview.html",
        job_id=job_id,
        preview=pub,
        meta=meta,
        schema_errors=errs,
        design_json=json.dumps(pub.get("extracted_design") or {}, ensure_ascii=False, indent=2),
    )


@app.post("/preview/<job_id>/supplement")
def supplement(job_id: str):
    if _rate_limited("supplement"):
        flash("请求过于频繁，请稍后再试（访问限流）。")
        return redirect(url_for("preview", job_id=job_id)), 429

    d = _job_dir(job_id, create=False)
    if d is None or not (d / "preview.json").exists():
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    preview = json.loads((d / "preview.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    table_text = (request.form.get("manual_table") or "").strip()
    if not table_text:
        flash("请粘贴表格内容")
        return redirect(url_for("preview", job_id=job_id))

    replaces = None
    for u in preview.get("unparsed_assets") or []:
        if u.get("asset_type") == "scanned_table":
            replaces = u.get("id")
            break

    upload_bin = d / "upload.bin"
    goal = meta.get("goal") or "unspecified"
    supplements = list(preview.get("manual_supplements") or [])
    supplements.append({
        "id": f"manual-{len(supplements)+1}",
        "kind": "table",
        "text": table_text,
        "source": "manual_input",
        "replaces_unparsed_asset_id": replaces,
    })

    try:
        if upload_bin.exists():
            new_preview = build_parse_preview(
                data=upload_bin.read_bytes(),
                filename=meta.get("filename") or "upload.bin",
                research_goal_level=goal,
                manual_supplements=supplements,
            )
        else:
            text = "\n\n".join(
                b.get("text") or ""
                for b in (preview.get("ingested_blocks") or [])
                if b.get("source") != "manual_input"
            )
            new_preview = build_parse_preview(
                protocol_text=text or "（原文本）",
                filename=meta.get("filename") or "pasted.md",
                research_goal_level=goal,
                manual_supplements=supplements,
            )
    except Exception as e:  # noqa: BLE001
        flash(f"合并表格失败：{type(e).__name__}: {e}")
        return redirect(url_for("preview", job_id=job_id))

    (d / "preview.json").write_text(json.dumps(new_preview, ensure_ascii=False, indent=2), encoding="utf-8")
    flash("已合并手动表格（source=manual_input）")
    return redirect(url_for("preview", job_id=job_id))


@app.post("/audit/<job_id>")
def audit(job_id: str):
    if _rate_limited("audit"):
        flash("请求过于频繁，请稍后再试（访问限流）。")
        return redirect(url_for("preview", job_id=job_id)), 429

    d = _job_dir(job_id, create=False)
    if d is None or not (d / "preview.json").exists():
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    preview = json.loads((d / "preview.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}

    override_raw = (request.form.get("design_override_json") or "").strip()
    override = None
    if override_raw:
        try:
            override = json.loads(override_raw)
        except json.JSONDecodeError as e:
            flash(f"design_override JSON 无效：{e}")
            return redirect(url_for("preview", job_id=job_id))

    goal = request.form.get("research_goal_level") or meta.get("goal") or "unspecified"
    notes = request.form.get("confirmation_notes") or ""

    try:
        report = run_audit(
            preview,
            confirm_design=True,
            design_override=override,
            research_goal_level=goal,
            discipline=meta.get("discipline") or "auto",
            confirmation_notes=notes,
        )
    except Exception as e:  # noqa: BLE001 — no traceback to browser
        flash(f"审查失败：{type(e).__name__}: {e}")
        return redirect(url_for("preview", job_id=job_id))

    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("report_view", job_id=job_id))


@app.get("/report/<job_id>")
def report_view(job_id: str):
    d = _job_dir(job_id, create=False)
    if d is None:
        flash("报告不存在或已过期")
        return redirect(url_for("index"))
    path = d / "report.json"
    if not path.exists():
        flash("报告不存在，请先确认解析并审查")
        return redirect(url_for("preview", job_id=job_id))
    report = json.loads(path.read_text(encoding="utf-8"))
    errs = validate("report", report)
    return render_template("report.html", job_id=job_id, report=report, schema_errors=errs)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "protocol-audit-beta",
        "version": "0.1.3.3",
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "rate_limit": {"window_s": RATE_LIMIT_WINDOW_S, "max": RATE_LIMIT_MAX},
        "job_ttl_hours": JOB_TTL_HOURS,
        "production": IS_PRODUCTION,
        "basic_auth_enabled": bool(_DEMO_PW),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5055"))
    # Never enable Flask debug in production/beta; opt-in only via PROTOCOL_AUDIT_DEBUG=1
    debug = (not IS_PRODUCTION) and os.environ.get("PROTOCOL_AUDIT_DEBUG", "").strip() in ("1", "true", "yes")
    app.run(host="127.0.0.1", port=port, debug=debug)
