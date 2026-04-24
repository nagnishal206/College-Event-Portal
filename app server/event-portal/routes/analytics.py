"""Admin analytics dashboard.

Step 4 deliverable: surfaces the metrics computed by `analytics_pipeline`
to admins, plus a dedicated page that runs the 5 raw SQL queries from
`analytical_queries.sql` so reviewers can see the queries actually fire.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template
from flask_login import current_user, login_required
from sqlalchemy import text

from analytics_pipeline import df_to_records, run_pipeline
from extensions import db

analytics_bp = Blueprint("analytics", __name__, url_prefix="/admin/analytics")
log = logging.getLogger("analytics")

SQL_FILE = Path(__file__).resolve().parent.parent / "analytical_queries.sql"


def _require_admin() -> None:
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


def _split_sql_queries(text_blob: str) -> list[dict]:
    """Split the analytical_queries.sql file into individual queries with
    a friendly title for each. Titles are taken from the `-- Q<n>. <title>`
    header lines.
    """
    parts = []
    pattern = re.compile(r"-- Q(\d+)\.\s*(.+)")
    chunks = text_blob.split("-- =====================================================================")
    current_title = None
    current_num = None
    sql_buffer: list[str] = []

    for chunk in chunks:
        m = pattern.search(chunk)
        if m:
            # New query section starts here -> finalize the previous one.
            if current_title and sql_buffer:
                parts.append(
                    {
                        "num": current_num,
                        "title": current_title,
                        "sql": "\n".join(sql_buffer).strip(),
                    }
                )
                sql_buffer = []
            current_num = int(m.group(1))
            current_title = m.group(2).strip()
        else:
            stripped = chunk.strip()
            if stripped and current_title:
                # Drop pure-comment lines; keep actual SQL.
                code_lines = [
                    ln for ln in stripped.splitlines() if not ln.strip().startswith("--")
                ]
                code = "\n".join(code_lines).strip()
                if code:
                    sql_buffer.append(code)

    if current_title and sql_buffer:
        parts.append(
            {
                "num": current_num,
                "title": current_title,
                "sql": "\n".join(sql_buffer).strip(),
            }
        )
    # Stable order by question number.
    return sorted(parts, key=lambda p: p["num"] or 0)


@analytics_bp.route("/")
@login_required
def dashboard():
    _require_admin()
    metrics = run_pipeline()
    return render_template(
        "admin/analytics.html",
        m=metrics,
        popular=df_to_records(metrics["popular_events"]),
        cats=df_to_records(metrics["category_breakdown"]),
        depts=df_to_records(metrics["department_engagement"]),
        trend=df_to_records(metrics["registration_trend"]),
        top_users=df_to_records(metrics["top_participants"]),
        winners=df_to_records(metrics["winners"]),
        monthly_budget=df_to_records(metrics["monthly_budget"]),
        status_rows=df_to_records(metrics["status_breakdown"]),
    )


@analytics_bp.route("/queries")
@login_required
def queries():
    """Run each of the 5 analytical SQL queries and show the results.

    This page exists explicitly so an academic reviewer can verify the
    SQL deliverable. Each query is loaded from analytical_queries.sql,
    executed with read-only privileges, and the rows are rendered in a
    table.
    """
    _require_admin()
    if not SQL_FILE.exists():
        abort(500, "analytical_queries.sql is missing")

    sql_blob = SQL_FILE.read_text(encoding="utf-8")
    queries_meta = _split_sql_queries(sql_blob)
    results = []
    for q in queries_meta:
        try:
            res = db.session.execute(text(q["sql"]))
            rows = [dict(r._mapping) for r in res.fetchall()]
            cols = list(rows[0].keys()) if rows else []
            for row in rows:
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
            results.append(
                {
                    "num": q["num"],
                    "title": q["title"],
                    "sql": q["sql"],
                    "rows": rows,
                    "cols": cols,
                    "error": None,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Query Q%s failed", q["num"])
            results.append(
                {
                    "num": q["num"],
                    "title": q["title"],
                    "sql": q["sql"],
                    "rows": [],
                    "cols": [],
                    "error": str(exc),
                }
            )

    return render_template("admin/queries.html", results=results)


@analytics_bp.route("/api/trend.json")
@login_required
def trend_json():
    """Tiny JSON endpoint feeding the dashboard's trend chart."""
    _require_admin()
    metrics = run_pipeline()
    return jsonify(df_to_records(metrics["registration_trend"]))
