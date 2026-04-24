"""Authentication blueprint: single login, register-with-OTP, verify, logout.

Flow
----
1. POST /register  -> validates input, hashes password, generates 6-digit
   OTP, stores everything in `pending_otps`, emails the OTP, redirects to
   /verify-otp?email=...
2. POST /verify-otp -> checks the OTP & expiry, copies the staged record
   into `users`, deletes the staging row, logs the user in, redirects.
3. POST /login -> single page; redirects admin -> /admin/portal,
   user -> /user/portal based on role.
4. GET  /logout -> session teardown.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from extensions import db
from models import PendingOtp, User
from services.email_service import EmailNotConfigured, send_otp_email

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger("auth")

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
DEPARTMENTS = [
    "Computer Science",
    "Information Technology",
    "Electronics",
    "Mechanical",
    "Civil",
    "Electrical",
    "Business Administration",
    "Mathematics",
    "Physics",
    "Chemistry",
    "Biotechnology",
    "Other",
]


def _portal_url_for(user: User) -> str:
    return url_for("admin.portal") if user.is_admin else url_for("user.portal")


def _generate_otp() -> str:
    # secrets.randbelow keeps it cryptographically random and zero-padded.
    return f"{secrets.randbelow(1_000_000):06d}"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_portal_url_for(current_user))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Please enter your email and password.", "danger")
            return render_template("auth/login.html", email=email), 400

        user = db.session.query(User).filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", email=email), 401

        login_user(user, remember=True)
        flash(f"Welcome back, {user.name}.", "success")
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(_portal_url_for(user))

    return render_template("auth/login.html", email="")


# ---------------------------------------------------------------------------
# Register (step 1: collect details, generate + send OTP)
# ---------------------------------------------------------------------------
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_portal_url_for(current_user))

    form = {
        "name": "",
        "email": "",
        "department": "",
        "role": "user",
    }

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        form["department"] = (request.form.get("department") or "").strip()
        form["role"] = (request.form.get("role") or "user").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        # ---- validation -------------------------------------------------
        errors: list[str] = []
        if len(form["name"]) < 2:
            errors.append("Name must be at least 2 characters.")
        try:
            v = validate_email(form["email"], check_deliverability=False)
            form["email"] = v.normalized.lower()
        except EmailNotValidError as exc:
            errors.append(str(exc))
        if form["department"] not in DEPARTMENTS:
            errors.append("Please choose a valid department.")
        if form["role"] not in {"admin", "user"}:
            errors.append("Role must be 'admin' or 'user'.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        existing = db.session.query(User).filter_by(email=form["email"]).first()
        if existing:
            errors.append("An account with this email already exists. Please sign in.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "auth/register.html", form=form, departments=DEPARTMENTS
            ), 400

        # ---- generate OTP, stage row, send email ------------------------
        otp_code = _generate_otp()
        password_hash = generate_password_hash(password)
        expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)

        try:
            # Replace any prior pending row for the same email.
            db.session.query(PendingOtp).filter_by(email=form["email"]).delete()
            pending = PendingOtp(
                email=form["email"],
                name=form["name"],
                department=form["department"],
                role=form["role"],
                password_hash=password_hash,
                otp_code=otp_code,
                expires_at=expires_at,
            )
            db.session.add(pending)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            log.exception("Failed staging pending OTP row")
            flash("Something went wrong saving your registration. Please try again.", "danger")
            return render_template(
                "auth/register.html", form=form, departments=DEPARTMENTS
            ), 500

        try:
            send_otp_email(form["email"], form["name"], otp_code)
        except EmailNotConfigured as exc:
            log.error("Gmail not configured: %s", exc)
            flash(f"Email service problem: {exc}", "danger")
            return render_template(
                "auth/register.html", form=form, departments=DEPARTMENTS
            ), 500
        except Exception as exc:  # pragma: no cover - SMTP failure paths
            log.exception("OTP email send failed")
            flash(f"Could not send the verification email: {exc}", "danger")
            return render_template(
                "auth/register.html", form=form, departments=DEPARTMENTS
            ), 502

        session["pending_email"] = form["email"]
        flash(
            f"We sent a 6-digit code to {form['email']}. Enter it below to "
            "finish creating your account.",
            "info",
        )
        # Pass the email as a query param too, in case the session cookie is
        # blocked (e.g. inside a cross-origin preview iframe).
        return redirect(url_for("auth.verify_otp", email=form["email"]))

    return render_template("auth/register.html", form=form, departments=DEPARTMENTS)


# ---------------------------------------------------------------------------
# Verify OTP (step 2: confirm + promote to users)
# ---------------------------------------------------------------------------
@auth_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = request.args.get("email") or session.get("pending_email") or ""
    email = email.strip().lower()

    if request.method == "POST":
        email = (request.form.get("email") or email).strip().lower()
        otp_input = (request.form.get("otp") or "").strip()

        pending = db.session.query(PendingOtp).filter_by(email=email).first()
        if not pending:
            flash("No pending verification for that email. Please register again.", "danger")
            return redirect(url_for("auth.register"))

        if pending.expires_at < datetime.utcnow():
            db.session.delete(pending)
            db.session.commit()
            flash("That code expired. Please register again to receive a new one.", "warning")
            return redirect(url_for("auth.register"))

        if pending.attempts >= OTP_MAX_ATTEMPTS:
            db.session.delete(pending)
            db.session.commit()
            flash("Too many invalid attempts. Please register again.", "danger")
            return redirect(url_for("auth.register"))

        if otp_input != pending.otp_code:
            pending.attempts += 1
            db.session.commit()
            remaining = OTP_MAX_ATTEMPTS - pending.attempts
            flash(
                f"Incorrect code. {remaining} attempt(s) remaining.",
                "danger",
            )
            return render_template("auth/verify_otp.html", email=email), 400

        # ---- promote to users ------------------------------------------
        try:
            user = User(
                name=pending.name,
                email=pending.email,
                password_hash=pending.password_hash,
                role=pending.role,
                department=pending.department,
            )
            db.session.add(user)
            db.session.delete(pending)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            log.exception("Failed promoting pending user to users table")
            flash("Could not complete sign-up. Please try again.", "danger")
            return render_template("auth/verify_otp.html", email=email), 500

        session.pop("pending_email", None)
        login_user(user, remember=True)
        flash(f"Welcome to the portal, {user.name}!", "success")
        return redirect(_portal_url_for(user))

    if not email:
        return redirect(url_for("auth.register"))
    return render_template("auth/verify_otp.html", email=email)


# ---------------------------------------------------------------------------
# Resend OTP (helper for the verify page)
# ---------------------------------------------------------------------------
@auth_bp.route("/resend-otp", methods=["POST"])
def resend_otp():
    email = (request.form.get("email") or session.get("pending_email") or "").strip().lower()
    pending = db.session.query(PendingOtp).filter_by(email=email).first()
    if not pending:
        flash("No pending verification for that email. Please register again.", "warning")
        return redirect(url_for("auth.register"))

    pending.otp_code = _generate_otp()
    pending.expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    pending.attempts = 0
    db.session.commit()

    try:
        send_otp_email(pending.email, pending.name, pending.otp_code)
    except Exception as exc:
        log.exception("Failed to resend OTP")
        flash(f"Could not resend the verification email: {exc}", "danger")
        return redirect(url_for("auth.verify_otp", email=email))

    flash("A fresh code is on its way to your inbox.", "info")
    return redirect(url_for("auth.verify_otp", email=email))


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("pending_email", None)
    flash("You have been signed out.", "info")
    return redirect(url_for("landing"))
