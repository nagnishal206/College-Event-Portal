"""Admin portal blueprint stub.

Step 4 fills this out with the analytics dashboard, approval queue, and
results management. For now we only need a landing page so the
post-login redirect works correctly.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin() -> None:
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


@admin_bp.route("/portal")
@login_required
def portal():
    _require_admin()
    return render_template("admin/portal.html")
