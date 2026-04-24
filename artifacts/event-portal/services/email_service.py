"""Gmail SMTP helper for the OTP verification flow.

Uses the standard library `smtplib` so no extra dependency is needed. The
sender authenticates with the `GMAIL_USER` + `GMAIL_APP_PASSWORD` env vars.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("email_service")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


class EmailNotConfigured(RuntimeError):
    """Raised when GMAIL_USER / GMAIL_APP_PASSWORD are missing."""


def _get_credentials() -> tuple[str, str]:
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise EmailNotConfigured(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set to send OTP emails."
        )
    return user, password


def send_otp_email(to_email: str, name: str, otp_code: str) -> None:
    """Send a 6-digit OTP to `to_email`. Raises on SMTP failure."""
    sender, password = _get_credentials()

    msg = EmailMessage()
    msg["Subject"] = f"Your verification code: {otp_code}"
    msg["From"] = f"College Event Portal <{sender}>"
    msg["To"] = to_email
    msg.set_content(
        f"""Hi {name},

Your one-time verification code for the College Event Intelligence Portal is:

    {otp_code}

This code expires in 10 minutes. If you did not request this, you can ignore
this email.

— College Event Portal
"""
    )
    msg.add_alternative(
        f"""\
<!doctype html>
<html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif;
                   background:#f1faee; padding:32px;">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;
              padding:32px;box-shadow:0 6px 24px rgba(29,53,87,.08);">
    <h2 style="color:#1d3557;margin:0 0 16px;">Verify your email</h2>
    <p style="color:#333;line-height:1.5;">
      Hi <strong>{name}</strong>, use the code below to finish creating your
      account on the College Event Intelligence Portal.
    </p>
    <div style="font-size:36px;font-weight:700;letter-spacing:.4em;
                color:#e63946;background:#f1faee;padding:20px 24px;
                text-align:center;border-radius:12px;margin:24px 0;">
      {otp_code}
    </div>
    <p style="color:#666;font-size:13px;line-height:1.5;">
      This code expires in 10 minutes. If you did not request it, you can
      safely ignore this message.
    </p>
  </div>
</body></html>
""",
        subtype="html",
    )

    log.info("Sending OTP email to %s", to_email)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    log.info("OTP email delivered to %s", to_email)
