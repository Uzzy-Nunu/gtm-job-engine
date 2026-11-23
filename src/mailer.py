"""Send email through Gmail (PRD §10.6 digest, §10.7 OP-3 alerts).

Uses Gmail's SMTP server with an app password, so the system can send mail but
can't read the inbox. Needs these GitHub Secrets:

  GMAIL_ADDRESS       the Gmail account that sends (e.g. you@gmail.com)
  GMAIL_APP_PASSWORD  a 16-character app password for that account
  DIGEST_TO_EMAIL     where digests and alerts go (optional; defaults to GMAIL_ADDRESS)

FakeMailer keeps messages in memory for tests and offline demos.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class MailError(RuntimeError):
    pass


def build_message(sender: str, to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"GTM Job Engine <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


class GmailMailer:
    def __init__(self, address: str | None = None, app_password: str | None = None,
                 to: str | None = None, smtp_factory=smtplib.SMTP_SSL):
        self.address = (address if address is not None else os.environ.get("GMAIL_ADDRESS", "")).strip()
        password = app_password if app_password is not None else os.environ.get("GMAIL_APP_PASSWORD", "")
        self.password = password.replace(" ", "").strip()   # Google shows it in groups of 4
        self.to = (to if to is not None else os.environ.get("DIGEST_TO_EMAIL", "")).strip() or self.address
        missing = [n for n, v in (("GMAIL_ADDRESS", self.address), ("GMAIL_APP_PASSWORD", self.password)) if not v]
        if missing:
            raise MailError(f"Missing GitHub Secret(s): {', '.join(missing)}. See docs/runbook.md > Email.")
        self._smtp = smtp_factory

    def send(self, subject: str, text: str, html: str | None = None) -> None:
        msg = build_message(self.address, self.to, subject, text, html)
        try:
            with self._smtp(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(self.address, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            raise MailError("Gmail refused the login. Check GMAIL_ADDRESS and that GMAIL_APP_PASSWORD is an "
                            f"app password (not your normal password). Code {e.smtp_code}.") from None
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(f"Could not send email through Gmail: {type(e).__name__}: {e}") from None


class FakeMailer:
    def __init__(self, to: str = "peace@example.com"):
        self.to = to
        self.sent: list[EmailMessage] = []

    def send(self, subject: str, text: str, html: str | None = None) -> None:
        self.sent.append(build_message("engine@example.com", self.to, subject, text, html))
