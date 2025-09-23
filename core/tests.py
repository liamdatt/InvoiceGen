from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from .models import Client, WhatsAppFollowUp, WhatsAppMessageLog, WhatsAppSettings
from .whatsapp import WhatsAppSendError, send_follow_up_message


class WhatsAppFollowUpModelTests(TestCase):
    def setUp(self) -> None:
        self.settings = WhatsAppSettings.load()
        self.settings.global_follow_up_days = 120
        self.settings.save()
        self.client = Client.objects.create(name="Alice", phone="+18761234567")

    def test_follow_up_defaults_to_global_interval(self) -> None:
        follow_up = WhatsAppFollowUp.objects.create(
            client=self.client,
            last_service_date=date(2024, 1, 1),
        )
        follow_up.refresh_schedule(settings=self.settings, commit=True)
        self.assertEqual(
            follow_up.next_follow_up_date,
            date(2024, 1, 1) + timedelta(days=120),
        )

    def test_follow_up_override_interval(self) -> None:
        follow_up = WhatsAppFollowUp.objects.create(
            client=self.client,
            last_service_date=date(2024, 1, 1),
            follow_up_days_override=45,
        )
        follow_up.refresh_schedule(settings=self.settings, commit=True)
        self.assertEqual(
            follow_up.next_follow_up_date,
            date(2024, 1, 1) + timedelta(days=45),
        )


class WhatsAppSendTests(TestCase):
    def setUp(self) -> None:
        self.settings = WhatsAppSettings.load()
        self.settings.global_follow_up_days = 30
        self.settings.business_name = "Test Garage"
        self.settings.save()
        settings.TWILIO_CONTENT_SID = "HX123"

    @patch("core.whatsapp._sender_number", return_value="whatsapp:+1234567890")
    @patch("core.whatsapp._twilio_client")
    def test_send_follow_up_success(self, mock_twilio_client: MagicMock, mock_sender: MagicMock) -> None:
        client = Client.objects.create(name="Bob", phone="+18761234567")
        follow_up = WhatsAppFollowUp.objects.create(
            client=client,
            last_service_date=timezone.localdate() - timedelta(days=60),
        )
        follow_up.refresh_schedule(settings=self.settings, commit=True)

        message_mock = MagicMock(sid="SM123", status="queued")
        mock_twilio_client.return_value.messages.create.return_value = message_mock

        result = send_follow_up_message(
            follow_up,
            trigger=WhatsAppMessageLog.Trigger.MANUAL,
            settings_obj=self.settings,
        )

        follow_up.refresh_from_db()
        self.assertEqual(result.sid, "SM123")
        self.assertIsNotNone(follow_up.last_sent_at)
        self.assertEqual(
            follow_up.next_follow_up_date,
            timezone.localdate() + timedelta(days=30),
        )
        log = WhatsAppMessageLog.objects.get()
        self.assertEqual(log.status, WhatsAppMessageLog.Status.SENT)
        self.assertEqual(log.trigger, WhatsAppMessageLog.Trigger.MANUAL)
        mock_twilio_client.return_value.messages.create.assert_called_once()
        kwargs = mock_twilio_client.return_value.messages.create.call_args.kwargs
        self.assertEqual(kwargs["from_"], "whatsapp:+1234567890")
        self.assertEqual(kwargs["to"], "whatsapp:+18761234567")
        self.assertEqual(kwargs["content_sid"], "HX123")
        variables = json.loads(kwargs["content_variables"])
        self.assertEqual(
            variables,
            {
                "1": "Bob",
                "2": "Test Garage",
                "3": "60",
                "4": follow_up.last_service_date.strftime("%B %d, %Y"),
            },
        )

    def test_send_follow_up_without_phone_raises(self) -> None:
        client = Client.objects.create(name="Charlie", phone="")
        follow_up = WhatsAppFollowUp.objects.create(client=client)

        with self.assertRaises(WhatsAppSendError):
            send_follow_up_message(
                follow_up,
                trigger=WhatsAppMessageLog.Trigger.MANUAL,
                settings_obj=self.settings,
            )

        self.assertFalse(WhatsAppMessageLog.objects.exists())
