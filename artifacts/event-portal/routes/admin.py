"""Admin portal blueprint.

Step 3 deliverables: full event lifecycle.
  * GET  /admin/portal              -> dashboard summary
  * GET  /admin/events              -> all events with status filter
  * GET  /admin/events/new          -> create event form
  * POST /admin/events              -> create (status=PENDING)
  * GET  /admin/events/<id>/edit    -> edit form
  * POST /admin/events/<id>         -> update event
  * POST /admin/events/<id>/approve -> set APPROVED
  * POST /admin/events/<id>/reject  -> set REJECTED
  * POST /admin/events/<id>/delete  -> remove event
  * GET  /admin/approvals           -> PENDING-only queue (shortcut)

The full analytics dashboard arrives in Step 4; results management arrives
in Step 6/7 as part of the analytics pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

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
from sqlalchemy import desc, func, select

from extensions import db
from models import Event, Registration, User

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger("admin")

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
STATUSES = ("PENDING", "APPROVED", "REJECTED")


def _require_admin() -> None:
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


def _get_event_or_404(event_id: int) -> Event:
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)
    return event


def _parse_event_form(form) -> tuple[dict, list[str]]:
    """Validate the event form and return (clean_data, errors)."""
    errors: list[str] = []
    name = (form.get("name") or "").strip()
    category = (form.get("category") or "").strip()
    venue = (form.get("venue") or "").strip()
    description = (form.get("description") or "").strip()
    date_raw = (form.get("date") or "").strip()
    budget_raw = (form.get("budget") or "0").strip()
    is_competition = bool(form.get("is_competition"))

    if len(name) < 3:
        errors.append("Event name must be at least 3 characters.")
    if category not in CATEGORIES:
        errors.append("Choose a valid category.")
    if not venue:
        errors.append("Venue is required.")

    event_date = None
    try:
        event_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError:
        errors.append("Provide a valid date (YYYY-MM-DD).")

    try:
        budget = Decimal(budget_raw or "0")
        if budget < 0:
            errors.append("Budget cannot be negative.")
    except InvalidOperation:
        errors.append("Budget must be a number.")
        budget = Decimal("0")

    return (
        {
            "name": name,
            "category": category,
            "venue": venue,
            "description": description,
            "date": event_date,
            "budget": budget,
            "is_competition": is_competition,
        },
        errors,
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin_bp.route("/portal")
@login_required
def portal():
    _require_admin()
    counts = {
        s: db.session.execute(
            select(func.count(Event.id)).where(Event.status == s)
        ).scalar_one()
        for s in STATUSES
    }
    total_events = sum(counts.values())
    total_users = db.session.execute(select(func.count(User.id))).scalar_one()
    total_regs = db.session.execute(select(func.count(Registration.id))).scalar_one()

    pending = (
        db.session.execute(
            select(Event)
            .where(Event.status == "PENDING")
            .order_by(desc(Event.created_at))
            .limit(5)
        )
        .scalars()
        .all()
    )
    recent_approved = (
        db.session.execute(
            select(Event)
            .where(Event.status == "APPROVED")
            .order_by(desc(Event.created_at))
            .limit(5)
        )
        .scalars()
        .all()
    )
    return render_template(
        "admin/portal.html",
        counts=counts,
        total_events=total_events,
        total_users=total_users,
        total_regs=total_regs,
        pending=pending,
        recent_approved=recent_approved,
    )


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------
@admin_bp.route("/events")
@login_required
def list_events():
    _require_admin()
    status_filter = (request.args.get("status") or "").upper().strip()

    stmt = (
        select(Event, func.count(Registration.id).label("reg_count"))
        .outerjoin(Registration, Registration.event_id == Event.id)
        .group_by(Event.id)
        .order_by(desc(Event.created_at))
    )
    if status_filter in STATUSES:
        stmt = stmt.where(Event.status == status_filter)

    rows = db.session.execute(stmt).all()
    return render_template(
        "admin/events_list.html",
        rows=rows,
        statuses=STATUSES,
        active_status=status_filter,
    )


@admin_bp.route("/events/new", methods=["GET", "POST"])
@login_required
def create_event():
    _require_admin()
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
        clean, errors = _parse_event_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "admin/event_form.html",
                form=form_state,
                categories=CATEGORIES,
                mode="create",
            ), 400

        event = Event(
            name=clean["name"],
            category=clean["category"],
            date=clean["date"],
            venue=clean["venue"],
            description=clean["description"],
            budget=clean["budget"],
            is_competition=clean["is_competition"],
            status="PENDING",
            created_by=current_user.id,
        )
        db.session.add(event)
        db.session.commit()
        flash(
            f'"{event.name}" was submitted and is awaiting approval.',
            "success",
        )
        return redirect(url_for("admin.list_events", status="PENDING"))

    return render_template(
        "admin/event_form.html",
        form=form_state,
        categories=CATEGORIES,
        mode="create",
    )


@admin_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id: int):
    _require_admin()
    event = _get_event_or_404(event_id)

    if request.method == "POST":
        clean, errors = _parse_event_form(request.form)
        form_state = request.form.to_dict()
        form_state["is_competition"] = bool(request.form.get("is_competition"))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "admin/event_form.html",
                form=form_state,
                categories=CATEGORIES,
                mode="edit",
                event=event,
            ), 400

        event.name = clean["name"]
        event.category = clean["category"]
        event.venue = clean["venue"]
        event.description = clean["description"]
        event.date = clean["date"]
        event.budget = clean["budget"]
        event.is_competition = clean["is_competition"]
        # Editing an event resets it to PENDING so it goes through approval
        # again — sensible policy for an academic project.
        event.status = "PENDING"
        db.session.commit()
        flash(
            f'"{event.name}" updated and re-submitted for approval.',
            "info",
        )
        return redirect(url_for("admin.list_events"))

    form_state = {
        "name": event.name,
        "category": event.category,
        "venue": event.venue,
        "description": event.description or "",
        "date": event.date.isoformat() if event.date else "",
        "budget": str(event.budget),
        "is_competition": event.is_competition,
    }
    return render_template(
        "admin/event_form.html",
        form=form_state,
        categories=CATEGORIES,
        mode="edit",
        event=event,
    )


@admin_bp.route("/events/<int:event_id>/approve", methods=["POST"])
@login_required
def approve_event(event_id: int):
    _require_admin()
    event = _get_event_or_404(event_id)
    event.status = "APPROVED"
    db.session.commit()
    flash(f'Approved "{event.name}".', "success")
    return redirect(request.referrer or url_for("admin.approvals"))


@admin_bp.route("/events/<int:event_id>/reject", methods=["POST"])
@login_required
def reject_event(event_id: int):
    _require_admin()
    event = _get_event_or_404(event_id)
    event.status = "REJECTED"
    db.session.commit()
    flash(f'Rejected "{event.name}".', "warning")
    return redirect(request.referrer or url_for("admin.approvals"))


@admin_bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event(event_id: int):
    _require_admin()
    event = _get_event_or_404(event_id)
    name = event.name
    db.session.delete(event)
    db.session.commit()
    flash(f'Deleted "{name}".', "info")
    return redirect(url_for("admin.list_events"))


# ---------------------------------------------------------------------------
# Approval queue (shortcut)
# ---------------------------------------------------------------------------
@admin_bp.route("/approvals")
@login_required
def approvals():
    _require_admin()
    pending = (
        db.session.execute(
            select(Event)
            .where(Event.status == "PENDING")
            .order_by(Event.date.asc())
        )
        .scalars()
        .all()
    )
    return render_template("admin/approvals.html", pending=pending)
