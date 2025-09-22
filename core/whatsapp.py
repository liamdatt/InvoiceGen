from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings

from .models import (
    WhatsAppFollowUp,
    WhatsAppMessageLog,
    WhatsAppSettings,
)

try:  # pragma: no cover - fallback when twilio isn't installed
    from twilio.base.exceptions import TwilioException  # type: ignore
except ImportError:  # pragma: no cover - handled gracefully
    class TwilioException(Exception):
        """Fallback Twilio exception when the SDK is not installed."""

        pass


class WhatsAppConfigurationError(RuntimeError):
    """Raised when the Twilio credentials are not configured."""


class WhatsAppSendError(RuntimeError):
    """Raised when sending a WhatsApp message fails."""


@dataclass
class WhatsAppSendResult:
    sid: str
    status: str


def _twilio_client() -> Any:
    try:
        from twilio.rest import Client as TwilioClient  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise WhatsAppConfigurationError(
            "Twilio SDK is not installed. Install the 'twilio' package to enable WhatsApp messaging."
        ) from exc
    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    if not account_sid or not auth_token:
        raise WhatsAppConfigurationError(
            "Twilio credentials are not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in the environment."
        )
    return TwilioClient(account_sid, auth_token)


def _sender_number() -> str:
    sender = getattr(settings, "TWILIO_WHATSAPP_FROM", None)
    if not sender:
        raise WhatsAppConfigurationError(
            "Twilio WhatsApp sender is not configured. Set TWILIO_WHATSAPP_FROM in the environment."
        )
    sender = sender.strip()
    if not sender.lower().startswith("whatsapp:"):
        sender = f"whatsapp:{sender}"
    return sender


_WHATSAPP_PREFIX_RE = re.compile(r"^whatsapp:", re.IGNORECASE)
_NON_DIGIT_RE = re.compile(r"[^0-9+]")


def normalise_whatsapp_number(phone: str) -> str:
    number = (phone or "").strip()
    if not number:
        raise WhatsAppSendError("Client does not have a phone number on file.")

    number = _WHATSAPP_PREFIX_RE.sub("", number)
    number = _NON_DIGIT_RE.sub("", number)
    if not number.startswith("+"):
        raise WhatsAppSendError("Client phone number must include the country code, e.g. +18761234567.")
    return f"whatsapp:{number}"


def send_follow_up_message(
    follow_up: WhatsAppFollowUp,
    *,
    trigger: str,
    settings_obj: Optional[WhatsAppSettings] = None,
) -> WhatsAppSendResult:
    settings_obj = settings_obj or WhatsAppSettings.load()
    body = follow_up.build_message(settings=settings_obj)
    to_number = normalise_whatsapp_number(follow_up.client.phone)
    client = _twilio_client()
    sender = _sender_number()

    try:
        message = client.messages.create(from_=sender, to=to_number, body=body)
    except TwilioException as exc:  # pragma: no cover - depends on network
        follow_up.register_failure(str(exc))
        WhatsAppMessageLog.objects.create(
            follow_up=follow_up,
            status=WhatsAppMessageLog.Status.FAILED,
            trigger=trigger,
            body=body,
            error_message=str(exc),
        )
        raise WhatsAppSendError(f"Failed to send WhatsApp message: {exc}") from exc

    follow_up.register_success(settings=settings_obj)
    WhatsAppMessageLog.objects.create(
        follow_up=follow_up,
        status=WhatsAppMessageLog.Status.SENT,
        trigger=trigger,
        body=body,
        twilio_sid=message.sid,
    )
    return WhatsAppSendResult(sid=message.sid, status=message.status or "sent")
