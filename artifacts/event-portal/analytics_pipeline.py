"""Pandas-based analytics pipeline for the College Event Portal.

Step 6 (Crucial Academic Requirement) will flesh this script out fully. This
file is the Step 1 skeleton: it already wires up SQLAlchemy + Pandas, exposes
a `run_pipeline()` entry point and writes aggregated summaries into a
`department_summary` table that the admin dashboard will read from.

Usage:
    python analytics_pipeline.py
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s analytics - %(message)s")
log = logging.getLogger("analytics_pipeline")


def _engine():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required to run the analytics pipeline.")
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg2://" + db_url[len("postgres://") :]
    return create_engine(db_url, pool_pre_ping=True)


def _clean_department(value: object) -> str:
    """Standardize department text - title-case and strip noise."""
    if value is None:
        return "Unknown"
    text_value = str(value).strip()
    if not text_value:
        return "Unknown"
    return " ".join(part.capitalize() for part in text_value.replace("_", " ").split())


def run_pipeline() -> dict[str, Any]:
    """Pull tables, clean them, compute aggregates, persist results.

    Returns a JSON-serializable dict so the admin dashboard can consume it
    directly (Step 4 will hit this from a Flask route).
    """
    engine = _engine()

    log.info("Loading source tables...")
    with engine.connect() as conn:
        users = pd.read_sql(text("SELECT * FROM users"), conn)
        events = pd.read_sql(text("SELECT * FROM events"), conn)
        registrations = pd.read_sql(text("SELECT * FROM registrations"), conn)
        results = pd.read_sql(text("SELECT * FROM results"), conn)

    # ---- Cleaning -----------------------------------------------------
    if not users.empty:
        users["department"] = users["department"].map(_clean_department)
    if not results.empty:
        results["prize"] = results["prize"].fillna("N/A")

    # ---- Aggregations -------------------------------------------------
    summary: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "totals": {
            "users": int(len(users)),
            "events": int(len(events)),
            "registrations": int(len(registrations)),
            "results": int(len(results)),
        },
    }

    if not events.empty and not users.empty:
        creators = events.merge(
            users[["id", "department"]], left_on="created_by", right_on="id", how="left"
        )
        dept_event_count = (
            creators.groupby("department")["id_x"].count().rename("event_count")
        )
        summary["events_by_department"] = dept_event_count.to_dict()
    else:
        summary["events_by_department"] = {}

    if not registrations.empty and not users.empty:
        reg = registrations.merge(
            users[["id", "department"]], left_on="user_id", right_on="id", how="left"
        )
        dept_reg = reg.groupby("department")["id_x"].count().rename("registration_count")
        summary["registrations_by_department"] = dept_reg.to_dict()

        participation_rate = (
            (dept_reg / users.groupby("department").size()).fillna(0).round(3)
        )
        summary["participation_rate_by_department"] = participation_rate.to_dict()
    else:
        summary["registrations_by_department"] = {}
        summary["participation_rate_by_department"] = {}

    if not events.empty:
        events["date"] = pd.to_datetime(events["date"])
        monthly = events.groupby(events["date"].dt.to_period("M")).size()
        summary["events_by_month"] = {str(k): int(v) for k, v in monthly.items()}
        budgets = events.groupby("category")["budget"].sum().round(2)
        summary["budget_by_category"] = {k: float(v) for k, v in budgets.items()}
    else:
        summary["events_by_month"] = {}
        summary["budget_by_category"] = {}

    # ---- Persist a tidy summary table for the dashboard --------------
    dept_rows = []
    for dept in set(summary["events_by_department"]) | set(
        summary["registrations_by_department"]
    ):
        dept_rows.append(
            {
                "department": dept,
                "event_count": int(summary["events_by_department"].get(dept, 0)),
                "registration_count": int(
                    summary["registrations_by_department"].get(dept, 0)
                ),
                "participation_rate": float(
                    summary["participation_rate_by_department"].get(dept, 0)
                ),
                "generated_at": summary["generated_at"],
            }
        )

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS department_summary (
                    department TEXT PRIMARY KEY,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    registration_count INTEGER NOT NULL DEFAULT 0,
                    participation_rate NUMERIC(6,3) NOT NULL DEFAULT 0,
                    generated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("DELETE FROM department_summary"))
        if dept_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO department_summary
                        (department, event_count, registration_count,
                         participation_rate, generated_at)
                    VALUES
                        (:department, :event_count, :registration_count,
                         :participation_rate, :generated_at)
                    """
                ),
                dept_rows,
            )

    log.info("Pipeline complete. %d department rows written.", len(dept_rows))
    return summary


if __name__ == "__main__":
    output = run_pipeline()
    print(json.dumps(output, indent=2, default=str))
