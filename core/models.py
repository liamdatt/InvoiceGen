from django.db import models
from django.conf import settings
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse

GCT_RATE = Decimal('0.15')


class Client(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Invoice(models.Model):
    class Type(models.TextChoices):
        GENERAL = 'GENERAL', 'General'
        PROFORMA = 'PROFORMA', 'Proforma'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='invoices')
    invoice_type = models.CharField(max_length=10, choices=Type.choices, default=Type.GENERAL)

    vehicle = models.CharField(max_length=255, blank=True)
    lic_no = models.CharField("Lic#", max_length=50, blank=True)
    chassis_no = models.CharField("Chassis#", max_length=100, blank=True)
    date = models.DateField()

    pdf_file = models.FileField(upload_to='invoices/', blank=True, null=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self) -> str:
        return f"{self.get_invoice_type_display()} #{self.pk or 'new'} - {self.client.name}"

    @property
    def parts_subtotal(self) -> Decimal:
        v = self.items.aggregate(total=models.Sum('parts_cost'))['total'] or Decimal('0')
        return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def labour_subtotal(self) -> Decimal:
        v = self.items.aggregate(total=models.Sum('labour_cost'))['total'] or Decimal('0')
        return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def gct(self) -> Decimal:
        return (self.parts_subtotal * GCT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return (self.parts_subtotal + self.labour_subtotal + self.gct).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def _money(self, v: Decimal) -> str:
        return f"${v:,.2f}"

    def generate_general_pdf(self, overwrite: bool = True) -> None:
        try:
            from weasyprint import HTML, default_url_fetcher
        except ImportError as exc:
            raise RuntimeError(
                "WeasyPrint is required to generate invoice PDFs. Install the 'weasyprint' package to enable this feature."
            ) from exc

        def django_url_fetcher(url: str):
            parsed = urlparse(url)

            if parsed.scheme in {"http", "https", "data"}:
                return default_url_fetcher(url)

            if settings.STATIC_URL and parsed.path.startswith(settings.STATIC_URL):
                relative_path = parsed.path[len(settings.STATIC_URL):]
                absolute_path = finders.find(relative_path)
                if isinstance(absolute_path, (list, tuple)):
                    absolute_path = absolute_path[0] if absolute_path else None
                if absolute_path:
                    return default_url_fetcher(Path(absolute_path).resolve().as_uri())

            if settings.MEDIA_URL and parsed.path.startswith(settings.MEDIA_URL):
                relative_path = parsed.path[len(settings.MEDIA_URL):]
                media_path = (settings.MEDIA_ROOT / relative_path).resolve()
                if media_path.exists():
                    return default_url_fetcher(media_path.as_uri())

            fallback_path = (settings.BASE_DIR / parsed.path.lstrip("/")).resolve()
            if fallback_path.exists():
                return default_url_fetcher(fallback_path.as_uri())

            return default_url_fetcher(url)

        logo_candidates = [
            settings.BASE_DIR / "invoicegen" / "resources" / "logo.jpeg",
            settings.BASE_DIR / "resources" / "logo.jpeg",
        ]
        logo_path = next((p for p in logo_candidates if p.exists()), None)

        html = render_to_string(
            "invoices/detail_pdf.html",
            {
                "invoice": self,
                "for_pdf": True,
                "logo_src": logo_path.resolve().as_uri() if logo_path else None,
            },
        )

        pdf_content = HTML(
            string=html,
            base_url=str(settings.BASE_DIR),
            url_fetcher=django_url_fetcher,
        ).write_pdf()

        filename = f"invoice-{self.pk}-general.pdf"
        if not self.pdf_file or overwrite:
            self.pdf_file.save(filename, ContentFile(pdf_content), save=True)


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    labour_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f"{self.description} (L:{self.labour_cost} P:{self.parts_cost})"
