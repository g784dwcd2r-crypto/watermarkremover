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


class LoggingEmailSender(EmailSender):
    """Records that an email was sent without recording its contents."""

    name = "logging"

    def send(self, message: OutboundEmail) -> None:
        logger.info(
            "transactional email dispatched",
            extra=log_context(kind=message.kind, subject=message.subject),
        )


_sender: EmailSender = LoggingEmailSender()


def set_email_sender(sender: EmailSender) -> None:
    global _sender
    _sender = sender


def get_email_sender() -> EmailSender:
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
    return None if settings.is_production else token


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
    return None if settings.is_production else token
