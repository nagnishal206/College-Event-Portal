"""Database models for the College Event Intelligence Portal.

Schema is normalized to 3NF. Four core tables:
  - users         -> account info + role (admin / user)
  - events        -> event metadata + approval status + competition flag
  - registrations -> M:N between users and events with timestamp
  - results       -> rank/prize per registration (only when event.is_competition)

Plus a small `pending_otps` table to support the OTP verification flow in
Step 2. Users only land in the `users` table after OTP verification.
"""

from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    department = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="users_role_check"),
    )

    events_created = relationship(
        "Event", back_populates="creator", cascade="all, delete-orphan"
    )
    registrations = relationship(
        "Registration", back_populates="user", cascade="all, delete-orphan"
    )

    # ----- helpers ------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.email} ({self.role})>"


class Event(db.Model):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    category = Column(String(80), nullable=False)
    date = Column(Date, nullable=False)
    venue = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    budget = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_competition = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="events_status_check",
        ),
    )

    creator = relationship("User", back_populates="events_created")
    registrations = relationship(
        "Registration", back_populates="event", cascade="all, delete-orphan"
    )

    @property
    def is_approved(self) -> bool:
        return self.status == "APPROVED"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.name} [{self.status}]>"


class Registration(db.Model):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "event_id", "user_id", name="registrations_event_user_unique"
        ),
    )

    event = relationship("Event", back_populates="registrations")
    user = relationship("User", back_populates="registrations")
    result = relationship(
        "Result",
        uselist=False,
        back_populates="registration",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Registration u={self.user_id} e={self.event_id}>"


class Result(db.Model):
    """Only populated for registrations whose event.is_competition is True."""

    __tablename__ = "results"

    id = Column(Integer, primary_key=True)
    registration_id = Column(
        Integer,
        ForeignKey("registrations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rank = Column(Integer, nullable=False)
    prize = Column(String(120), nullable=True)

    __table_args__ = (
        CheckConstraint("rank > 0", name="results_rank_positive"),
    )

    registration = relationship("Registration", back_populates="result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Result reg={self.registration_id} rank={self.rank}>"


class PendingOtp(db.Model):
    """Holds unverified registration data + OTP until the user verifies.

    Step 2 stores the candidate user here; once the OTP is verified the row
    is converted into a `users` record and deleted.
    """

    __tablename__ = "pending_otps"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    department = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    password_hash = Column(String(255), nullable=False)
    otp_code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PendingOtp {self.email}>"
