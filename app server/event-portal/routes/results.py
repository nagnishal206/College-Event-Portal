"""Admin-only routes for managing competition results.

Tied into the Event lifecycle (Step 3): when an event has
`is_competition = True`, the admin can record one Result per Registration
(rank + prize description). These rows then power the winners section of
the analytics dashboard.
"""

from __future__ import annotations

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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Event, Registration, Result, User

results_bp = Blueprint("results", __name__, url_prefix="/admin/results")


def _require_admin() -> None:
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


@results_bp.route("/")
@login_required
def index():
    _require_admin()
    competitions = (
        db.session.execute(
            select(Event)
            .where(Event.is_competition.is_(True), Event.status == "APPROVED")
            .order_by(Event.date.desc())
        )
        .scalars()
        .all()
    )
    return render_template("admin/results_index.html", competitions=competitions)


@results_bp.route("/<int:event_id>", methods=["GET", "POST"])
@login_required
def manage(event_id: int):
    _require_admin()
    event = db.session.get(Event, event_id)
    if not event or not event.is_competition:
        abort(404)

    if request.method == "POST":
        registration_id = request.form.get("registration_id", type=int)
        rank = request.form.get("rank", type=int)
        prize = (request.form.get("prize") or "").strip() or None

        reg = db.session.get(Registration, registration_id) if registration_id else None
        if not reg or reg.event_id != event.id:
            flash("Pick a valid registration for this event.", "danger")
        elif not rank or rank < 1:
            flash("Rank must be a positive integer.", "danger")
        else:
            existing = db.session.execute(
                select(Result).where(Result.registration_id == reg.id)
            ).scalar_one_or_none()
            try:
                if existing:
                    existing.rank = rank
                    existing.prize = prize
                    flash("Result updated.", "info")
                else:
                    db.session.add(
                        Result(registration_id=reg.id, rank=rank, prize=prize)
                    )
                    flash("Result recorded.", "success")
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Could not save result (constraint violation).", "danger")
        return redirect(url_for("results.manage", event_id=event.id))

    rows = db.session.execute(
        select(Registration, User, Result)
        .join(User, User.id == Registration.user_id)
        .outerjoin(Result, Result.registration_id == Registration.id)
        .where(Registration.event_id == event.id)
        .order_by(User.name)
    ).all()

    return render_template("admin/results_manage.html", event=event, rows=rows)


@results_bp.route("/<int:event_id>/<int:result_id>/delete", methods=["POST"])
@login_required
def delete(event_id: int, result_id: int):
    _require_admin()
    res = db.session.get(Result, result_id)
    if not res:
        abort(404)
    db.session.delete(res)
    db.session.commit()
    flash("Result removed.", "info")
    return redirect(url_for("results.manage", event_id=event_id))
