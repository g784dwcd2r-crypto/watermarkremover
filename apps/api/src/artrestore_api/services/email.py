"""Transactional email.

No SMTP provider is bundled. The shipped sender logs a redacted record of what
*would* be sent and, outside production, hands the token back through the API so
the reset and passwordless flows are fully exercisable locally. Wire a real
provider by implementing :class:`EmailSender` and passing it to
:func:`set_email_sender` at startup.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import log_context

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OutboundEmail:
    to: str
    subject: str
    body: str
    kind: str


class EmailSender(ABC):
    @abstractmethod
    def send(self, message: OutboundEmail) -> None: ...


class SMTPEmailSender(EmailSender):
    """Plain SMTP delivery with STARTTLS.

    Deliberately provider-agnostic: any transactional service that speaks SMTP
    (Postmark, SES, Mailgun, a relay of your own) works with four environment
    variables and no vendor SDK.
    """

    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        sender: str = "",
        starttls: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender or username
        self.starttls = starttls
        self.timeout = timeout

    def send(self, message: OutboundEmail) -> None:
        import smtplib
        from email.message import EmailMessage

        mail = EmailMessage()
        mail["From"] = self.sender
        mail["To"] = message.to
        mail["Subject"] = message.subject
        mail.set_content(message.body)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as connection:
            if self.starttls:
                connection.starttls()
            if self.username:
                connection.login(self.username, self.password)
            connection.send_message(mail)
        logger.info(
            "transactional email sent over smtp",
            extra=log_context(kind=message.kind, subject=message.subject),
        )


class LoggingEmailSender(EmailSender):
    """Records that an email was sent without recording its contents."""

    name = "logging"

    def send(self, message: OutboundEmail) -> None:
        logger.info(
            "transactional email dispatched",
            extra=log_context(kind=message.kind, subject=message.subject),
        )


_sender: EmailSender | None = None


def set_email_sender(sender: EmailSender | None) -> None:
    global _sender
    _sender = sender


def get_email_sender() -> EmailSender:
    """The active sender: explicit override, SMTP when configured, else logging."""
    global _sender
    if _sender is None:
        settings = get_settings()
        if settings.smtp_host:
            _sender = SMTPEmailSender(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                sender=settings.smtp_from,
                starttls=settings.smtp_starttls,
            )
        else:
            _sender = LoggingEmailSender()
    return _sender


def send_password_reset(email: str, token: str) -> str | None:
    """Send a reset link. Returns the token only outside production."""
    settings = get_settings()
    link = f"{settings.public_web_url}/reset-password?token={token}"
    get_email_sender().send(
        OutboundEmail(
            to=email,
            subject=f"Reset your {settings.app_name} password",
            body=f"Use this link within one hour to choose a new password: {link}",
            kind="password_reset",
        )
    )
    if settings.is_production or isinstance(get_email_sender(), SMTPEmailSender):
        return None
    return token


def send_magic_link(email: str, token: str) -> str | None:
    settings = get_settings()
    link = f"{settings.public_web_url}/login?token={token}"
    get_email_sender().send(
        OutboundEmail(
            to=email,
            subject=f"Your {settings.app_name} sign-in link",
            body=f"Use this link within 15 minutes to sign in: {link}",
            kind="magic_link",
        )
    )
    if settings.is_production or isinstance(get_email_sender(), SMTPEmailSender):
        return None
    return token
