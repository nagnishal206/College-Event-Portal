"""College Event Intelligence Portal - Flask application entry point.

Step 1 deliverable: foundation app + DB schema bootstrap. Subsequent steps
will mount auth blueprints, admin/user portals, and analytics endpoints.

Run locally:
    PORT=5000 BASE_PATH=/ python app.py
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, url_for
from flask_login import current_user

from extensions import db, login_manager

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("event-portal")


def _normalize_db_url(url: str) -> str:
    """Ensure SQLAlchemy uses the psycopg2 dialect and SSL where appropriate."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    parsed = urlparse(url)
    # Add sslmode=require if connecting to a remote host without one specified.
    if parsed.hostname and parsed.hostname not in {"localhost", "127.0.0.1"}:
        if "sslmode=" not in (parsed.query or ""):
            sep = "&" if parsed.query else "?"
            url = f"{url}{sep}sslmode=require"
    return url


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    secret = os.environ.get("SESSION_SECRET") or os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        # Dev fallback; production should always set SESSION_SECRET.
        secret = "dev-only-not-secret-please-set-SESSION_SECRET"
        log.warning("SESSION_SECRET not set - using insecure dev fallback.")
    app.secret_key = secret

    # Prefer an explicit APP_DATABASE_URL (e.g. user-provided Neon URL) so we
    # don't fight the platform-managed DATABASE_URL secret.
    db_url = (
        os.environ.get("APP_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not db_url:
        raise RuntimeError(
            "APP_DATABASE_URL / DATABASE_URL is not set. "
            "Provision a PostgreSQL database first."
        )
    normalized_url = _normalize_db_url(db_url)
    log.info(
        "Using database host=%s",
        urlparse(normalized_url).hostname,
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = normalized_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    base_path = os.environ.get("BASE_PATH", "/")
    app.config["APPLICATION_ROOT"] = base_path
    app.config["BASE_PATH"] = base_path

    db.init_app(app)
    login_manager.init_app(app)

    # User loader for Flask-Login (imported lazily to avoid circular import).
    from models import User  # noqa: WPS433

    @login_manager.user_loader
    def load_user(user_id: str):  # type: ignore[override]
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # Make current_user / base path available to all templates.
    @app.context_processor
    def inject_globals():  # noqa: WPS430
        return {
            "current_user": current_user,
            "base_path": base_path,
            "site_name": "College Event Intelligence Portal",
        }

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    from routes.auth import auth_bp  # noqa: WPS433
    from routes.admin import admin_bp  # noqa: WPS433
    from routes.user import user_bp  # noqa: WPS433

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)

    # ------------------------------------------------------------------
    # Top-level routes
    # ------------------------------------------------------------------
    @app.route("/")
    def landing():
        if current_user.is_authenticated:
            target = "admin.portal" if current_user.is_admin else "user.portal"
            return redirect(url_for(target))
        return render_template("landing.html")

    @app.route("/healthz")
    def healthz():
        try:
            db.session.execute(db.text("SELECT 1"))
            return {"status": "ok", "db": "ok"}
        except Exception as exc:  # pragma: no cover - diagnostic
            log.exception("DB healthcheck failed")
            return {"status": "degraded", "db": str(exc)}, 500

    # Bootstrap tables on first run. In production we'd use Alembic; for an
    # academic project create_all is acceptable and matches the spec.
    with app.app_context():
        db.create_all()
        log.info("Database tables verified / created.")

    return app


app = create_app()


if __name__ == "__main__":
    raw_port = os.environ.get("PORT")
    if not raw_port:
        raise RuntimeError("PORT environment variable is required.")
    port = int(raw_port)
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    log.info("Starting Flask on 0.0.0.0:%s (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
