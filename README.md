# College Event Intelligence Portal

## Overview

A Flask-based web portal for managing college events, built to satisfy strict
academic requirements (Pandas data processing pipeline + complex analytical
SQL queries). The user/admin portal lives at `artifacts/event-portal/`.

## Stack

- **Backend**: Python 3.11 + Flask 3
- **Database**: PostgreSQL (Replit-provisioned, accessed via `DATABASE_URL`)
- **ORM**: SQLAlchemy 2 + Flask-SQLAlchemy
- **Auth**: Flask-Login + Werkzeug password hashing (Gmail OTP coming in step 2)
- **Data pipeline**: Pandas + SQLAlchemy (`analytics_pipeline.py`)
- **Frontend**: Jinja2 templates + Bootstrap 5 (CDN)
- **Production server**: Gunicorn

## Project structure

```
artifacts/event-portal/
├── app.py                    Flask app factory + entrypoint
├── extensions.py             Shared db / login_manager singletons
├── models.py                 SQLAlchemy models (3NF schema)
├── analytics_pipeline.py     Pandas pipeline (academic deliverable)
├── analytical_queries.sql    5 stakeholder SQL queries (academic deliverable)
├── routes/                   Flask blueprints (filled in steps 2-5)
├── templates/                Jinja2 templates
└── static/                   CSS / images
```

## Database schema (Step 1 - DONE)

Normalized to 3NF:

| Table          | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `users`        | id, name, email, password_hash, role, department     |
| `events`       | id, name, category, date, venue, description, budget, status, created_by, is_competition |
| `registrations`| id, event_id, user_id, timestamp                     |
| `results`      | id, registration_id, rank, prize                     |
| `pending_otps` | Step 2 OTP staging table                             |

`status` is constrained to `PENDING / APPROVED / REJECTED`. `role` is
constrained to `admin / user`. Foreign keys cascade on delete.

## Build plan (per the user's spec)

1. **Database setup & flexible schema** — DONE
2. Authentication & OTP flow (Gmail SMTP)
3. Event approval pipeline (token system)
4. Admin portal (analytics dashboard, approvals, results)
5. User portal (discovery, 1-click register, propose event)
6. Pandas data processing pipeline (`analytics_pipeline.py` full version)
7. Analytical SQL deliverables (`analytical_queries.sql` expanded)

The user wants explicit confirmation between each step.

## Running locally

The artifact is wired to run via the workspace's preview proxy:

- Dev: `python app.py` (PORT and BASE_PATH are injected by the artifact runner)
- Prod: `gunicorn -b 0.0.0.0:$PORT -w 2 app:app`
- Health check: `GET /healthz`

## Required environment / secrets

| Name                  | Purpose                              | Status                |
| --------------------- | ------------------------------------ | --------------------- |
| `DATABASE_URL`        | PostgreSQL connection                | provisioned           |
| `SESSION_SECRET`      | Flask session signing                | already in workspace  |
| `GMAIL_USER`          | Sender email for OTP (Step 2)        | will request in Step 2|
| `GMAIL_APP_PASSWORD`  | Gmail App Password (Step 2)          | will request in Step 2|
