"""Pandas analytics pipeline for the College Event Intelligence Portal.

This module is the *required* data-processing layer for the academic
deliverable. It pulls raw rows out of PostgreSQL via SQLAlchemy, loads them
into Pandas DataFrames, and produces the aggregated metrics consumed by the
admin analytics dashboard (Step 4).

Public entry point:
    run_pipeline(engine) -> dict

The returned dictionary has Pandas DataFrames / scalars, one key per
analytics product. Templates render them directly.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine

from extensions import db

log = logging.getLogger("analytics_pipeline")


# ---------------------------------------------------------------------------
# Extraction (E)
# ---------------------------------------------------------------------------
def _read_table(engine: Engine, table: str) -> pd.DataFrame:
    """Read a whole table into a DataFrame. Tiny helper for clarity."""
    return pd.read_sql_table(table, con=engine)


def _extract(engine: Engine) -> dict[str, pd.DataFrame]:
    return {
        "users": _read_table(engine, "users"),
        "events": _read_table(engine, "events"),
        "registrations": _read_table(engine, "registrations"),
        "results": _read_table(engine, "results"),
    }


# ---------------------------------------------------------------------------
# Transformation (T) helpers
# ---------------------------------------------------------------------------
def _normalize(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Normalize column names + types so downstream code is consistent."""
    users = frames["users"].rename(columns={"id": "user_id"})
    events = frames["events"].rename(columns={"id": "event_id"})
    regs = frames["registrations"].rename(columns={"id": "registration_id"})
    results = frames["results"]

    if not events.empty:
        events["date"] = pd.to_datetime(events["date"]).dt.date
        events["budget"] = pd.to_numeric(events["budget"], errors="coerce").fillna(0)
    if not regs.empty:
        regs["timestamp"] = pd.to_datetime(regs["timestamp"])
    return {"users": users, "events": events, "registrations": regs, "results": results}


def _empty_metrics() -> dict[str, Any]:
    """Return empty placeholders when there's no data yet."""
    empty = pd.DataFrame()
    return {
        "totals": {
            "users": 0,
            "events": 0,
            "approved_events": 0,
            "registrations": 0,
            "competitions": 0,
            "avg_regs_per_event": 0.0,
        },
        "popular_events": empty,
        "category_breakdown": empty,
        "department_engagement": empty,
        "registration_trend": empty,
        "top_participants": empty,
        "winners": empty,
        "monthly_budget": empty,
        "status_breakdown": empty,
    }


# ---------------------------------------------------------------------------
# Transformation (T) - per metric
# ---------------------------------------------------------------------------
def _totals(d: dict[str, pd.DataFrame]) -> dict[str, Any]:
    events = d["events"]
    approved = events[events["status"] == "APPROVED"] if not events.empty else events
    avg = (
        len(d["registrations"]) / len(approved) if len(approved) else 0.0
    )
    return {
        "users": len(d["users"]),
        "events": len(events),
        "approved_events": len(approved),
        "registrations": len(d["registrations"]),
        "competitions": int(events["is_competition"].sum()) if not events.empty else 0,
        "avg_regs_per_event": round(float(avg), 2),
    }


def _popular_events(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Top 10 events by registration count, joined with event metadata."""
    regs, events = d["registrations"], d["events"]
    if regs.empty or events.empty:
        return pd.DataFrame()
    counts = (
        regs.groupby("event_id").size().rename("registrations").reset_index()
    )
    merged = counts.merge(events, on="event_id", how="inner")
    merged = merged[merged["status"] == "APPROVED"]
    merged = merged.sort_values("registrations", ascending=False).head(10)
    return merged[
        ["name", "category", "date", "venue", "registrations", "is_competition"]
    ].reset_index(drop=True)


def _category_breakdown(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Registrations + event counts grouped by category."""
    regs, events = d["registrations"], d["events"]
    if events.empty:
        return pd.DataFrame()
    ev_counts = (
        events.groupby("category").size().rename("events_count").reset_index()
    )
    if regs.empty:
        ev_counts["registrations"] = 0
        return ev_counts.sort_values("events_count", ascending=False).reset_index(drop=True)
    joined = regs.merge(events[["event_id", "category"]], on="event_id", how="left")
    reg_counts = (
        joined.groupby("category").size().rename("registrations").reset_index()
    )
    out = ev_counts.merge(reg_counts, on="category", how="left").fillna({"registrations": 0})
    out["registrations"] = out["registrations"].astype(int)
    return out.sort_values("registrations", ascending=False).reset_index(drop=True)


def _department_engagement(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """For each department: members, total regs, unique events attended."""
    users, regs = d["users"], d["registrations"]
    if users.empty:
        return pd.DataFrame()
    members = users.groupby("department").size().rename("members").reset_index()
    if regs.empty:
        members["registrations"] = 0
        members["unique_events"] = 0
        return members.sort_values("members", ascending=False).reset_index(drop=True)
    joined = regs.merge(users[["user_id", "department"]], on="user_id", how="left")
    reg_counts = joined.groupby("department").size().rename("registrations").reset_index()
    unique = (
        joined.groupby("department")["event_id"].nunique().rename("unique_events").reset_index()
    )
    out = members.merge(reg_counts, on="department", how="left").merge(
        unique, on="department", how="left"
    )
    out = out.fillna({"registrations": 0, "unique_events": 0})
    out["registrations"] = out["registrations"].astype(int)
    out["unique_events"] = out["unique_events"].astype(int)
    out["engagement_rate"] = (
        out["registrations"] / out["members"].replace(0, pd.NA)
    ).round(2)
    return out.sort_values("registrations", ascending=False).reset_index(drop=True)


def _registration_trend(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily registration counts over the last 30 days (for trend chart)."""
    regs = d["registrations"]
    if regs.empty:
        return pd.DataFrame()
    end = date.today()
    start = end - timedelta(days=29)
    df = regs.copy()
    df["day"] = df["timestamp"].dt.date
    daily = df.groupby("day").size().rename("registrations").reset_index()
    full_range = pd.DataFrame(
        {"day": pd.date_range(start, end, freq="D").date}
    )
    out = full_range.merge(daily, on="day", how="left").fillna({"registrations": 0})
    out["registrations"] = out["registrations"].astype(int)
    return out


def _top_participants(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Top 10 students by registration count."""
    users, regs = d["users"], d["registrations"]
    if regs.empty or users.empty:
        return pd.DataFrame()
    counts = regs.groupby("user_id").size().rename("registrations").reset_index()
    merged = counts.merge(users, on="user_id", how="left")
    merged = merged[merged["role"] == "user"]
    merged = merged.sort_values("registrations", ascending=False).head(10)
    return merged[["name", "email", "department", "registrations"]].reset_index(drop=True)


def _winners(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """All recorded competition winners (rank=1) with event + user info."""
    results, regs, events, users = (
        d["results"],
        d["registrations"],
        d["events"],
        d["users"],
    )
    if results.empty:
        return pd.DataFrame()
    df = results.merge(regs, left_on="registration_id", right_on="registration_id", how="left")
    df = df.merge(
        events[["event_id", "name", "category", "date"]].rename(columns={"name": "event_name"}),
        on="event_id",
        how="left",
    )
    df = df.merge(
        users[["user_id", "name", "department"]].rename(columns={"name": "winner"}),
        on="user_id",
        how="left",
    )
    df = df.sort_values(["date", "event_name", "rank"])
    return df[
        ["event_name", "category", "date", "winner", "department", "rank", "prize"]
    ].reset_index(drop=True)


def _monthly_budget(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Monthly approved-event budget totals."""
    events = d["events"]
    if events.empty:
        return pd.DataFrame()
    ap = events[events["status"] == "APPROVED"].copy()
    if ap.empty:
        return pd.DataFrame()
    ap["month"] = pd.to_datetime(ap["date"]).dt.to_period("M").astype(str)
    out = (
        ap.groupby("month")
        .agg(events=("event_id", "count"), total_budget=("budget", "sum"))
        .reset_index()
        .sort_values("month")
    )
    out["total_budget"] = out["total_budget"].astype(float).round(2)
    return out


def _status_breakdown(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    events = d["events"]
    if events.empty:
        return pd.DataFrame()
    out = events.groupby("status").size().rename("events").reset_index()
    return out.sort_values("events", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public pipeline entry point
# ---------------------------------------------------------------------------
def run_pipeline(engine: Engine | None = None) -> dict[str, Any]:
    """Execute the full Extract -> Transform pipeline and return all metrics.

    Pass an explicit SQLAlchemy `engine` if you want to call this from a
    script. When called from a Flask request the default `db.engine` works.
    """
    eng = engine or db.engine
    log.info("Running analytics pipeline")
    raw = _extract(eng)
    frames = _normalize(raw)

    if all(frames[k].empty for k in ("events", "registrations", "users")):
        return _empty_metrics()

    return {
        "totals": _totals(frames),
        "popular_events": _popular_events(frames),
        "category_breakdown": _category_breakdown(frames),
        "department_engagement": _department_engagement(frames),
        "registration_trend": _registration_trend(frames),
        "top_participants": _top_participants(frames),
        "winners": _winners(frames),
        "monthly_budget": _monthly_budget(frames),
        "status_breakdown": _status_breakdown(frames),
    }


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Jinja-friendly conversion that handles dates and Decimals nicely."""
    if df is None or df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out.to_dict(orient="records")
