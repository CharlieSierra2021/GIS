"""Shared Jinja2 environment for server-rendered API pages.

Reuses the reports template directory (``src/reports/templates``); the
customer portal templates live in its ``portal/`` subdirectory. Autoescape
is on — same defence-in-depth posture as the report renderer.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "reports" / "templates"


def make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(default=True),
    )
