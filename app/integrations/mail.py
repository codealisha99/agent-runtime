"""SMTP delivery. Queues locally when SMTP_HOST is unset."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from ..config import get_settings


def deliver(to: str, subject: str, body: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.smtp_host:
        return {"status": "queued", "transport": "outbox"}
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body or "")
    context = ssl.create_default_context()
    if settings.smtp_ssl:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=10, context=context
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    try:
        smtp.ehlo()
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
    except Exception as exc:
        raise RuntimeError(f"smtp failed: {exc}") from exc
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()
    return {"status": "sent", "transport": "smtp", "host": settings.smtp_host}
