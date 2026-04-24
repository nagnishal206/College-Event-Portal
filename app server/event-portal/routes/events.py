"""Public event browsing + 1-click registration (Steps 3 + 5)."""

from __future__ import annotations

import logging
from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import asc, func, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Event, Registration

events_bp = Blueprint("events", __name__, url_prefix="/events")
log = logging.getLogger("events")


@events_bp.route("/")
@login_required
def list_events():
    category = (request.args.get("category") or "").strip()
    when = (request.args.get("when") or "upcoming").strip().lower()

    stmt = (
        select(Event, func.count(Registration.id).label("reg_count"))
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

    # Pre-compute which events the current user is already registered for.
    my_event_ids = set(
        db.session.execute(
            select(Registration.event_id).where(
                Registration.user_id == current_user.id
            )
        ).scalars()
    )

    events = [
        {"event": e, "reg_count": c, "is_registered": e.id in my_event_ids}
        for e, c in rows
    ]

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
    my_reg = db.session.execute(
        select(Registration).where(
            Registration.event_id == event.id,
            Registration.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    return render_template(
        "events/detail.html",
        event=event,
        reg_count=reg_count,
        my_reg=my_reg,
    )


@events_bp.route("/<int:event_id>/register", methods=["POST"])
@login_required
def register(event_id: int):
    event = db.session.get(Event, event_id)
    if not event or event.status != "APPROVED":
        abort(404)
    if event.date < date.today():
        flash("This event has already happened.", "warning")
        return redirect(url_for("events.detail", event_id=event.id))
    if current_user.is_admin:
        flash("Admins manage events; only students register.", "warning")
        return redirect(url_for("events.detail", event_id=event.id))

    try:
        reg = Registration(event_id=event.id, user_id=current_user.id)
        db.session.add(reg)
        db.session.commit()
        flash(f'You are registered for "{event.name}". See you there!', "success")
    except IntegrityError:
        db.session.rollback()
        flash("You are already registered for this event.", "info")
    return redirect(url_for("events.detail", event_id=event.id))


@events_bp.route("/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel(event_id: int):
    reg = db.session.execute(
        select(Registration).where(
            Registration.event_id == event_id,
            Registration.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if not reg:
        flash("You aren't registered for this event.", "info")
    else:
        db.session.delete(reg)
        db.session.commit()
        flash("Your registration has been cancelled.", "info")
    return redirect(url_for("events.detail", event_id=event_id))
