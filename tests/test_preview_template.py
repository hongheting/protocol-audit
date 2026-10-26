"""Compile web Jinja templates so a delimiter typo cannot 500 /preview again.

Production failed after a successful async parse: preview.html opened a slice
with ``{{`` and closed it with ``%}`` (``[:160] %}``). jinja2 raises
TemplateSyntaxError before the page can render. No LLM.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parents[1] / "web" / "templates"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)))


def test_preview_template_compiles():
    template = _env().get_template("preview.html")
    assert template.name == "preview.html"
    src = (TEMPLATES / "preview.html").read_text(encoding="utf-8")
    assert "[:160] %}" not in src
    assert "{{ (b.text or '')[:160] }}" in src


def test_web_templates_compile():
    env = _env()
    names = sorted(p.name for p in TEMPLATES.glob("*.html"))
    assert "preview.html" in names
    for name in names:
        env.get_template(name)
