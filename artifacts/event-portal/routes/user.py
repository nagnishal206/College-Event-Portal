"""User portal blueprint stub.

Step 5 fills this out with discovery, registration and event proposals.
For now this just provides the landing page that the post-login redirect
sends regular users to.
"""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/portal")
@login_required
def portal():
    return render_template("user/portal.html")
