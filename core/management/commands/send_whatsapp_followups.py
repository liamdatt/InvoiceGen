from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import WhatsAppFollowUp, WhatsAppMessageLog, WhatsAppSettings
from core.whatsapp import (
    WhatsAppConfigurationError,
    WhatsAppSendError,
    send_follow_up_message,
)


class Command(BaseCommand):
    help = "Send scheduled WhatsApp follow-up messages."

    def handle(self, *args, **options):
        settings_obj = WhatsAppSettings.load()
        today = timezone.localdate()
        due_followups = WhatsAppFollowUp.objects.select_related('client').filter(
            is_active=True,
            next_follow_up_date__isnull=False,
            next_follow_up_date__lte=today,
        )

        if not due_followups.exists():
            self.stdout.write(self.style.SUCCESS("No WhatsApp follow-ups due."))
            return

        for follow_up in due_followups:
            client_name = follow_up.client.name
            try:
                send_follow_up_message(
                    follow_up,
                    trigger=WhatsAppMessageLog.Trigger.SCHEDULED,
                    settings_obj=settings_obj,
                )
            except WhatsAppConfigurationError as exc:
                self.stderr.write(self.style.ERROR(f"Configuration error sending to {client_name}: {exc}"))
                break
            except WhatsAppSendError as exc:
                self.stderr.write(self.style.ERROR(f"Failed to send to {client_name}: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Sent WhatsApp follow-up to {client_name}."))
