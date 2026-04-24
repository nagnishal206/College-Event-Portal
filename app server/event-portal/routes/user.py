"""Student portal blueprint (Step 5 deliverable).

Provides:
  * /user/portal              -> personal dashboard
  * /user/my-events           -> list of registrations
  * POST /events/<id>/register   (mounted in events_bp) -> 1-click signup
  * POST /events/<id>/cancel     (mounted in events_bp) -> cancel signup
  * /user/propose             -> propose a new event (lands as PENDING)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from werkzeug.utils import secure_filename

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    current_app,
)
from flask_login import current_user, login_required
from sqlalchemy import asc, func, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Event, Registration, Result

user_bp = Blueprint("user", __name__, url_prefix="/user")
log = logging.getLogger("user")

CATEGORIES = [
    "Technical",
    "Cultural",
    "Sports",
    "Workshop",
    "Seminar",
    "Hackathon",
    "Community",
    "Other",
]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@user_bp.route("/portal")
@login_required
def portal():
    upcoming_count = db.session.execute(
        select(func.count(Event.id)).where(
            Event.status == "APPROVED", Event.date >= date.today()
        )
    ).scalar_one()
    my_regs = db.session.execute(
        select(func.count(Registration.id)).where(
            Registration.user_id == current_user.id
        )
    ).scalar_one()
    next_events = (
        db.session.execute(
            select(Event)
            .where(Event.status == "APPROVED", Event.date >= date.today())
            .order_by(asc(Event.date))
            .limit(3)
        )
        .scalars()
        .all()
    )
    my_proposals = db.session.execute(
        select(func.count(Event.id)).where(Event.created_by == current_user.id)
    ).scalar_one()
    return render_template(
        "user/portal.html",
        upcoming_count=upcoming_count,
        my_regs=my_regs,
        next_events=next_events,
        my_proposals=my_proposals,
    )


# ---------------------------------------------------------------------------
# My events
# ---------------------------------------------------------------------------
@user_bp.route("/my-events")
@login_required
def my_events():
    rows = db.session.execute(
        select(Registration, Event, Result)
        .join(Event, Event.id == Registration.event_id)
        .outerjoin(Result, Result.registration_id == Registration.id)
        .where(Registration.user_id == current_user.id)
        .order_by(Event.date.desc())
    ).all()
    return render_template("user/my_events.html", rows=rows)


# ---------------------------------------------------------------------------
# Propose an event (lands in PENDING for admin approval)
# ---------------------------------------------------------------------------
@user_bp.route("/propose", methods=["GET", "POST"])
@login_required
def propose():
    form_state = {
        "name": "",
        "category": "",
        "venue": "",
        "description": "",
        "date": "",
        "budget": "0",
        "is_competition": False,
    }

    if request.method == "POST":
        form_state.update(request.form.to_dict())
        form_state["is_competition"] = bool(request.form.get("is_competition"))
        errors: list[str] = []
        name = form_state["name"].strip()
        category = form_state["category"].strip()
        venue = form_state["venue"].strip()
        description = (form_state["description"] or "").strip()
        date_raw = form_state["date"].strip()
        budget_raw = (form_state["budget"] or "0").strip()
        if len(name) < 3:
            errors.append("Event name must be at least 3 characters.")
        if category not in CATEGORIES:
            errors.append("Choose a valid category.")
        if not venue:
            errors.append("Venue is required.")
        try:
            event_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            if event_date < date.today():
                errors.append("Date cannot be in the past.")
        except ValueError:
            event_date = None
            errors.append("Provide a valid date (YYYY-MM-DD).")
        try:
            budget = Decimal(budget_raw or "0")
            if budget < 0:
                errors.append("Budget cannot be negative.")
        except InvalidOperation:
            budget = Decimal("0")
            errors.append("Budget must be a number.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "user/propose.html", form=form_state, categories=CATEGORIES, today=date.today().strftime('%Y-%m-%d')
            ), 400

        event = Event(
            name=name,
            category=category,
            date=event_date,
            venue=venue,
            description=description,
            budget=budget,
            is_competition=form_state["is_competition"],
            status="PENDING",
            created_by=current_user.id,
        )
        db.session.add(event)
        db.session.flush() # get event.id

        poster_file = request.files.get("poster")
        if poster_file and poster_file.filename:
            filename = secure_filename(f"event_{event.id}_{poster_file.filename}")
            filepath = os.path.join(current_app.root_path, "static", "posters", filename)
            poster_file.save(filepath)
            event.poster = filename

        db.session.commit()
        flash(
            f'Thanks! "{name}" was submitted and is awaiting admin approval.',
            "success",
        )
        return redirect(url_for("user.my_proposals"))

    return render_template(
        "user/propose.html", form=form_state, categories=CATEGORIES, today=date.today().strftime('%Y-%m-%d')
    )


@user_bp.route("/proposals")
@login_required
def my_proposals():
    proposals = (
        db.session.execute(
            select(Event)
            .where(Event.created_by == current_user.id)
            .order_by(Event.created_at.desc())
        )
        .scalars()
        .all()
    )
    return render_template("user/proposals.html", proposals=proposals)
