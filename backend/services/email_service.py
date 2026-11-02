"""
services/email_service.py — Ignis

Gmail SMTP, matching Prototype 1. Requires a Gmail App Password (not your
normal login password) — set up under Google Account > Security > App
Passwords, with 2-Step Verification enabled on the account first.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import os
import config


def send_email(subject: str, body: str, attachment_path: str | None = None) -> tuple[bool, str]:
    """Sends an email, optionally with a JPEG snapshot attached.
    Returns (success, error_detail).
    """
    if not config.EMAIL_ENABLED:
        return False, "Email not configured (missing sender, app password, or recipient)"

    msg = MIMEMultipart()
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                img = MIMEImage(f.read(), name=os.path.basename(attachment_path))
                msg.attach(img)
        except OSError as e:
            body += f"\n\n(Could not attach snapshot: {e})"

    try:
        with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
            server.sendmail(config.EMAIL_SENDER, config.EMAIL_RECIPIENT, msg.as_string())
        return True, ""
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except OSError as e:
        return False, f"Connection error: {e}"
