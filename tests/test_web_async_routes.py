"""Light tests for async upload/audit web routes (no real LLM)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTOCOL_AUDIT_ASYNC", "1")
    monkeypatch.delenv("PROTOCOL_AUDIT_ENV", raising=False)
    monkeypatch.delenv("PROTOCOL_AUDIT_DEMO_PASSWORD", raising=False)
    monkeypatch.delenv("PROTOCOL_AUDIT_BASIC_PASSWORD", raising=False)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    import app as webapp  # noqa: WPS433

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(webapp, "JOBS", jobs)
    monkeypatch.setattr(webapp, "ASYNC_ENABLED", True)
    monkeypatch.setattr(webapp, "_DEMO_PW", "")
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client(), webapp, jobs


def test_health_reports_async_version(client):
    c, webapp, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["version"] == webapp.APP_VERSION
    assert body.get("async") is True


def test_upload_redirects_to_wait_without_blocking(client):
    c, webapp, jobs = client
    started = {"n": 0}

    def slow_parse(**kwargs):
        started["n"] += 1
        time.sleep(0.35)
        return {
            "schema_version": "0.2.1",
            "source_file": kwargs.get("filename") or "pasted.md",
            "ingested_blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "x" * 50}],
            "extracted_design": {"research_goal_level": "unspecified"},
            "parse_warnings": [],
            "unparsed_assets": [],
            "tables_parsed_count": 0,
            "limited_audit_recommended": False,
            "manual_supplements": [],
        }

    # Keep patch alive until background worker finishes (thread runs after HTTP returns).
    with mock.patch.object(webapp, "build_parse_preview", side_effect=slow_parse):
        t0 = time.time()
        r = c.post(
            "/upload",
            data={
                "protocol_text": (
                    "这是一段用于异步上传测试的实验方案文本，"
                    "长度必须足够超过四十个汉字字符门槛，再补若干字。"
                ),
                "research_goal_level": "unspecified",
                "discipline": "auto",
            },
            follow_redirects=False,
        )
        elapsed = time.time() - t0

        assert r.status_code in (302, 303)
        loc = r.headers.get("Location") or ""
        assert "/jobs/" in loc and "wait" in loc and "phase=parse" in loc
        assert elapsed < 0.25, f"upload blocked too long: {elapsed:.3f}s"

        job_id = loc.rstrip("/").split("/jobs/")[1].split("/")[0]
        st_path = jobs / job_id / "parse_status.json"
        deadline = time.time() + 2.0
        while time.time() < deadline and not st_path.exists():
            time.sleep(0.05)
        assert st_path.exists()

        deadline = time.time() + 3.0
        while time.time() < deadline and not (jobs / job_id / "preview.json").exists():
            time.sleep(0.05)
        assert (jobs / job_id / "preview.json").exists()
        assert started["n"] >= 1

        st = c.get(f"/jobs/{job_id}/status?phase=parse")
        assert st.status_code == 200
        body = st.get_json()
        assert body["status"] == "done"
        assert "/preview/" in body["redirect"]


def test_status_done_when_preview_exists(client):
    c, webapp, jobs = client
    jid = "a" * 32
    d = jobs / jid
    d.mkdir()
    (d / "preview.json").write_text(
        json.dumps(
            {
                "schema_version": "0.2.1",
                "source_file": "t.md",
                "ingested_blocks": [],
                "extracted_design": {},
                "parse_warnings": [],
                "unparsed_assets": [],
            }
        ),
        encoding="utf-8",
    )
    webapp._write_status(d, "parse", status="done", started_at=time.time())
    r = c.get(f"/jobs/{jid}/status?phase=parse")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "done"
    assert "/preview/" in body["redirect"]


def test_atomic_write_json(client):
    _, webapp, jobs = client
    p = jobs / "x.json"
    webapp._atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1
    assert not list(jobs.glob("*.tmp"))
