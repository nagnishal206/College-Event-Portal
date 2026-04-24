"""Student portal blueprint.

Step 5 will add 1-click registration and event proposals. For now it shows
a friendly summary plus a quick link into the public event browser.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import asc, func, select

from extensions import db
from models import Event, Registration

user_bp = Blueprint("user", __name__, url_prefix="/user")


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
    return render_template(
        "user/portal.html",
        upcoming_count=upcoming_count,
        my_regs=my_regs,
        next_events=next_events,
    )
