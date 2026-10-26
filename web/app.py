"""ProtocolAudit V0.1.3.3-async2 Beta — Flask UI (async upload/parse + audit).

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
- async parse/audit (default) to avoid ACA/gateway 504 on long LLM calls
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

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
# Default async ON; set PROTOCOL_AUDIT_ASYNC=0 to force synchronous (legacy) path.
ASYNC_ENABLED = os.environ.get("PROTOCOL_AUDIT_ASYNC", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
APP_VERSION = "0.1.3.3-async2"

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
# In-process lock so the same job does not spawn duplicate workers.
_job_locks: dict[str, threading.Lock] = {}
_job_locks_guard = threading.Lock()


def _lock_for(jid: str) -> threading.Lock:
    with _job_locks_guard:
        lock = _job_locks.get(jid)
        if lock is None:
            lock = threading.Lock()
            _job_locks[jid] = lock
        return lock


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


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via temp file + replace (thread-safe enough for status files)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _status_path(d: Path, phase: str) -> Path:
    if phase == "audit":
        return d / "audit_status.json"
    return d / "parse_status.json"


def _read_status(d: Path, phase: str) -> dict | None:
    path = _status_path(d, phase)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _write_status(d: Path, phase: str, **fields) -> dict:
    payload = {"phase": phase, **fields}
    if "updated_at" not in payload:
        payload["updated_at"] = time.time()
    _atomic_write_json(_status_path(d, phase), payload)
    return payload


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


def _run_parse_worker(jid: str) -> None:
    """Background: build_parse_preview → preview.json + parse_status."""
    d = _job_dir(jid, create=False)
    if d is None:
        return
    lock = _lock_for(jid)
    if not lock.acquire(blocking=False):
        return
    try:
        st = _read_status(d, "parse") or {}
        if st.get("status") == "done" and (d / "preview.json").exists():
            return
        _write_status(d, "parse", status="running", started_at=st.get("started_at") or time.time())
        meta = {}
        if (d / "meta.json").exists():
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        goal = meta.get("goal") or "unspecified"
        filename = meta.get("filename") or "upload.bin"
        try:
            if (d / "upload.bin").exists():
                preview = build_parse_preview(
                    data=(d / "upload.bin").read_bytes(),
                    filename=filename,
                    research_goal_level=goal,
                )
            elif (d / "pasted.txt").exists():
                text = (d / "pasted.txt").read_text(encoding="utf-8")
                preview = build_parse_preview(
                    protocol_text=text,
                    filename=filename or "pasted.md",
                    research_goal_level=goal,
                )
            else:
                raise FileNotFoundError("neither upload.bin nor pasted.txt found")
            _atomic_write_json(d / "preview.json", preview)
            _write_status(
                d,
                "parse",
                status="done",
                started_at=st.get("started_at"),
                finished_at=time.time(),
            )
        except Exception as e:  # noqa: BLE001
            _write_status(
                d,
                "parse",
                status="error",
                started_at=st.get("started_at"),
                finished_at=time.time(),
                error=f"{type(e).__name__}: {e}",
            )
    finally:
        lock.release()


def _run_audit_worker(jid: str) -> None:
    """Background: run_audit → report.json + audit_status."""
    d = _job_dir(jid, create=False)
    if d is None:
        return
    lock = _lock_for(f"{jid}:audit")
    if not lock.acquire(blocking=False):
        return
    try:
        st = _read_status(d, "audit") or {}
        if st.get("status") == "done" and (d / "report.json").exists():
            return
        _write_status(d, "audit", status="running", started_at=st.get("started_at") or time.time())
        try:
            if not (d / "preview.json").exists():
                raise FileNotFoundError("preview.json missing")
            preview = json.loads((d / "preview.json").read_text(encoding="utf-8"))
            meta = {}
            if (d / "meta.json").exists():
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            req: dict = {}
            if (d / "audit_request.json").exists():
                req = json.loads((d / "audit_request.json").read_text(encoding="utf-8"))
            report = run_audit(
                preview,
                confirm_design=True,
                design_override=req.get("design_override"),
                research_goal_level=req.get("research_goal_level") or meta.get("goal") or "unspecified",
                discipline=meta.get("discipline") or "auto",
                confirmation_notes=req.get("confirmation_notes") or "",
            )
            _atomic_write_json(d / "report.json", report)
            _write_status(
                d,
                "audit",
                status="done",
                started_at=st.get("started_at"),
                finished_at=time.time(),
            )
        except Exception as e:  # noqa: BLE001
            _write_status(
                d,
                "audit",
                status="error",
                started_at=st.get("started_at"),
                finished_at=time.time(),
                error=f"{type(e).__name__}: {e}",
            )
    finally:
        lock.release()


def _start_parse_thread(jid: str) -> None:
    t = threading.Thread(target=_run_parse_worker, args=(jid,), daemon=True, name=f"parse-{jid[:8]}")
    t.start()


def _start_audit_thread(jid: str) -> None:
    t = threading.Thread(target=_run_audit_worker, args=(jid,), daemon=True, name=f"audit-{jid[:8]}")
    t.start()


@app.before_request
def _before():
    # Occasional cleanup (cheap) — every ~32nd request by time bucket
    if int(time.time()) % 32 == 0:
        _cleanup_expired_jobs()


@app.get("/")
def index():
    return render_template("index.html", async_enabled=ASYNC_ENABLED, app_version=APP_VERSION)


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
            _atomic_write_json(
                d / "meta.json",
                {
                    "filename": filename,
                    "goal": goal,
                    "discipline": discipline,
                    "created_at": time.time(),
                    "privacy_note": (
                        "unpublished protocol retained on server for JOB_TTL only; "
                        "not sent to public literature search by default"
                    ),
                },
            )
            if not ASYNC_ENABLED:
                preview = build_parse_preview(
                    data=data,
                    filename=filename,
                    research_goal_level=goal,
                )
                _atomic_write_json(d / "preview.json", preview)
                return redirect(url_for("preview", job_id=jid))
        elif len(text) >= 40:
            if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
                flash("粘贴文本过大。")
                return redirect(url_for("index"))
            (d / "pasted.txt").write_text(text, encoding="utf-8")
            _atomic_write_json(
                d / "meta.json",
                {
                    "filename": "pasted.md",
                    "goal": goal,
                    "discipline": discipline,
                    "created_at": time.time(),
                    "privacy_note": "unpublished protocol retained on server for JOB_TTL only",
                },
            )
            if not ASYNC_ENABLED:
                preview = build_parse_preview(
                    protocol_text=text,
                    filename="pasted.md",
                    research_goal_level=goal,
                )
                _atomic_write_json(d / "preview.json", preview)
                return redirect(url_for("preview", job_id=jid))
        else:
            flash("请上传 Word/PDF/Markdown，或粘贴不少于 40 字的方案文本。")
            return redirect(url_for("index"))
    except Exception as e:  # noqa: BLE001 — user-facing; no traceback
        flash(f"解析失败：{type(e).__name__}: {e}")
        return redirect(url_for("index"))

    # Async path: mark running and return immediately (do not wait for LLM).
    existing = _read_status(d, "parse")
    if existing and existing.get("status") == "running":
        return redirect(url_for("job_wait", job_id=jid, phase="parse"))
    if (d / "preview.json").exists():
        return redirect(url_for("preview", job_id=jid))
    _write_status(d, "parse", status="running", started_at=time.time())
    _start_parse_thread(jid)
    return redirect(url_for("job_wait", job_id=jid, phase="parse"))


@app.get("/jobs/<job_id>/wait")
def job_wait(job_id: str):
    phase = (request.args.get("phase") or "parse").strip().lower()
    if phase not in ("parse", "audit"):
        phase = "parse"
    d = _job_dir(job_id, create=False)
    if d is None:
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    # If already finished, skip wait page.
    if phase == "parse" and (d / "preview.json").exists():
        st = _read_status(d, "parse")
        if not st or st.get("status") != "error":
            return redirect(url_for("preview", job_id=job_id))
    if phase == "audit" and (d / "report.json").exists():
        st = _read_status(d, "audit")
        if not st or st.get("status") != "error":
            return redirect(url_for("report_view", job_id=job_id))
    # Kick worker again if status says running but result missing (e.g. process restart).
    st = _read_status(d, phase)
    if st and st.get("status") == "running":
        if phase == "parse" and not (d / "preview.json").exists():
            _start_parse_thread(job_id)
        elif phase == "audit" and not (d / "report.json").exists():
            _start_audit_thread(job_id)
    return render_template(
        "wait.html",
        job_id=job_id,
        phase=phase,
        app_version=APP_VERSION,
    )


@app.get("/jobs/<job_id>/status")
def job_status(job_id: str):
    phase = (request.args.get("phase") or "parse").strip().lower()
    if phase not in ("parse", "audit"):
        phase = "parse"
    d = _job_dir(job_id, create=False)
    if d is None:
        return jsonify({"phase": phase, "status": "error", "error": "任务不存在或已过期"}), 404

    result_file = d / ("preview.json" if phase == "parse" else "report.json")
    st = _read_status(d, phase) or {}

    if result_file.exists() and st.get("status") != "error":
        done_url = url_for("preview" if phase == "parse" else "report_view", job_id=job_id)
        return jsonify(
            {
                "phase": phase,
                "status": "done",
                "redirect": done_url,
                "started_at": st.get("started_at"),
                "finished_at": st.get("finished_at") or time.time(),
            }
        )

    status = st.get("status") or "unknown"
    payload = {
        "phase": phase,
        "status": status,
        "started_at": st.get("started_at"),
        "updated_at": st.get("updated_at"),
        "error": st.get("error"),
    }
    if status == "error":
        payload["home"] = url_for("index")
        if phase == "audit" and (d / "preview.json").exists():
            payload["preview"] = url_for("preview", job_id=job_id)
    return jsonify(payload)


@app.get("/preview/<job_id>")
def preview(job_id: str):
    d = _job_dir(job_id, create=False)
    if d is None:
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    path = d / "preview.json"
    if not path.exists():
        st = _read_status(d, "parse")
        if st and st.get("status") == "running":
            return redirect(url_for("job_wait", job_id=job_id, phase="parse"))
        if st and st.get("status") == "error":
            flash(f"解析失败：{st.get('error') or '未知错误'}")
            return redirect(url_for("index"))
        flash("任务不存在或已过期")
        return redirect(url_for("index"))
    preview_obj = json.loads(path.read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    pub = public_preview(preview_obj)
    errs = validate("preview", pub)
    return render_template(
        "preview.html",
        job_id=job_id,
        preview=pub,
        meta=meta,
        schema_errors=errs,
        design_json=json.dumps(pub.get("extracted_design") or {}, ensure_ascii=False, indent=2),
        async_enabled=ASYNC_ENABLED,
        app_version=APP_VERSION,
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
    preview_obj = json.loads((d / "preview.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    table_text = (request.form.get("manual_table") or "").strip()
    if not table_text:
        flash("请粘贴表格内容")
        return redirect(url_for("preview", job_id=job_id))

    replaces = None
    for u in preview_obj.get("unparsed_assets") or []:
        if u.get("asset_type") == "scanned_table":
            replaces = u.get("id")
            break

    upload_bin = d / "upload.bin"
    goal = meta.get("goal") or "unspecified"
    supplements = list(preview_obj.get("manual_supplements") or [])
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
                for b in (preview_obj.get("ingested_blocks") or [])
                if b.get("source") != "manual_input"
            )
            if not text and (d / "pasted.txt").exists():
                text = (d / "pasted.txt").read_text(encoding="utf-8")
            new_preview = build_parse_preview(
                protocol_text=text or "（原文本）",
                filename=meta.get("filename") or "pasted.md",
                research_goal_level=goal,
                manual_supplements=supplements,
            )
    except Exception as e:  # noqa: BLE001
        flash(f"合并表格失败：{type(e).__name__}: {e}")
        return redirect(url_for("preview", job_id=job_id))

    _atomic_write_json(d / "preview.json", new_preview)
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
    preview_obj = json.loads((d / "preview.json").read_text(encoding="utf-8"))
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

    if not ASYNC_ENABLED:
        try:
            report = run_audit(
                preview_obj,
                confirm_design=True,
                design_override=override,
                research_goal_level=goal,
                discipline=meta.get("discipline") or "auto",
                confirmation_notes=notes,
            )
        except Exception as e:  # noqa: BLE001 — no traceback to browser
            flash(f"审查失败：{type(e).__name__}: {e}")
            return redirect(url_for("preview", job_id=job_id))
        _atomic_write_json(d / "report.json", report)
        return redirect(url_for("report_view", job_id=job_id))

    # Async: persist request, start worker, redirect to wait (no LLM wait in HTTP).
    existing = _read_status(d, "audit")
    if existing and existing.get("status") == "running" and not (d / "report.json").exists():
        return redirect(url_for("job_wait", job_id=job_id, phase="audit"))
    if (d / "report.json").exists() and (not existing or existing.get("status") != "error"):
        # Allow re-run: clear old report when user re-confirms
        pass
    _atomic_write_json(
        d / "audit_request.json",
        {
            "design_override": override,
            "research_goal_level": goal,
            "confirmation_notes": notes,
            "queued_at": time.time(),
        },
    )
    # Drop stale report so status polling does not short-circuit to old result.
    report_path = d / "report.json"
    if report_path.exists():
        try:
            report_path.unlink()
        except OSError:
            pass
    _write_status(d, "audit", status="running", started_at=time.time())
    _start_audit_thread(job_id)
    return redirect(url_for("job_wait", job_id=job_id, phase="audit"))


@app.get("/report/<job_id>")
def report_view(job_id: str):
    d = _job_dir(job_id, create=False)
    if d is None:
        flash("报告不存在或已过期")
        return redirect(url_for("index"))
    path = d / "report.json"
    if not path.exists():
        st = _read_status(d, "audit")
        if st and st.get("status") == "running":
            return redirect(url_for("job_wait", job_id=job_id, phase="audit"))
        flash("报告不存在，请先确认解析并审查")
        return redirect(url_for("preview", job_id=job_id))
    report = json.loads(path.read_text(encoding="utf-8"))
    errs = validate("report", report)
    return render_template(
        "report.html",
        job_id=job_id,
        report=report,
        schema_errors=errs,
        app_version=APP_VERSION,
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "protocol-audit-beta",
        "version": APP_VERSION,
        "async": ASYNC_ENABLED,
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
