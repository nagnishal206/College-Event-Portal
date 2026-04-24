"""Public event browsing routes (visible to any signed-in user).

Only events whose `status == 'APPROVED'` are exposed here. Step 5 will add
the 1-click registration UX for students; this blueprint keeps things
read-only for now so the lifecycle is testable end-to-end.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, render_template, request
from flask_login import login_required
from sqlalchemy import asc, func, select

from extensions import db
from models import Event, Registration

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.route("/")
@login_required
def list_events():
    """Public listing of APPROVED events with simple filters."""
    category = (request.args.get("category") or "").strip()
    when = (request.args.get("when") or "upcoming").strip().lower()

    stmt = (
        select(
            Event,
            func.count(Registration.id).label("reg_count"),
        )
        .outerjoin(Registration, Registration.event_id == Event.id)
        .where(Event.status == "APPROVED")
        .group_by(Event.id)
        .order_by(asc(Event.date), asc(Event.name))
    )

    if category:
        stmt = stmt.where(Event.category == category)
    if when == "upcoming":
        stmt = stmt.where(Event.date >= date.today())
    elif when == "past":
        stmt = stmt.where(Event.date < date.today())

    rows = db.session.execute(stmt).all()
    events = [{"event": e, "reg_count": c} for e, c in rows]

    categories = (
        db.session.execute(
            select(Event.category)
            .where(Event.status == "APPROVED")
            .distinct()
            .order_by(Event.category)
        )
        .scalars()
        .all()
    )

    return render_template(
        "events/list.html",
        events=events,
        categories=categories,
        active_category=category,
        active_when=when,
    )


@events_bp.route("/<int:event_id>")
@login_required
def detail(event_id: int):
    event = db.session.get(Event, event_id)
    if not event or event.status != "APPROVED":
        abort(404)
    reg_count = db.session.execute(
        select(func.count(Registration.id)).where(Registration.event_id == event.id)
    ).scalar_one()
    return render_template(
        "events/detail.html", event=event, reg_count=reg_count
    )
