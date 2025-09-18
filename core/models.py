from __future__ import annotations

from django.db import models
from django.conf import settings
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from decimal import Decimal, ROUND_HALF_UP

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

    proforma_make = models.CharField("Make", max_length=100, blank=True)
    proforma_model = models.CharField("Model", max_length=100, blank=True)
    proforma_year = models.PositiveIntegerField("Year", blank=True, null=True)
    proforma_colour = models.CharField("Colour", max_length=50, blank=True)
    proforma_cc_rating = models.CharField("CC Rating", max_length=50, blank=True)
    proforma_price = models.DecimalField("Total Cost", max_digits=15, decimal_places=2, blank=True, null=True)
    proforma_currency = models.CharField("Currency", max_length=10, blank=True, default="JMD")

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

    def _money(self, v: Decimal | None, currency: str | None = None) -> str:
        if v is None:
            return ""
        amount = v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        currency = (currency or '').strip()
        if currency:
            return f"{currency} {amount:,.2f}"
        return f"${amount:,.2f}"

    @property
    def proforma_total_formatted(self) -> str:
        return self._money(self.proforma_price, self.proforma_currency)

    def _generate_pdf(self, template_name: str, filename: str, overwrite: bool = True) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError, sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is required to generate invoice PDFs. Install the 'playwright' package and its browsers with "
                "'playwright install chromium'."
            ) from exc

        logo_candidates = [
            settings.BASE_DIR / "invoicegen" / "resources" / "logo.jpeg",
            settings.BASE_DIR / "resources" / "logo.jpeg",
        ]
        logo_path = next((p for p in logo_candidates if p.exists()), None)

        # Convert logo to data URL for reliable PDF embedding
        logo_data_url = None
        if logo_path and logo_path.exists():
            try:
                import base64
                with open(logo_path, "rb") as f:
                    logo_data = f.read()
                    logo_data_url = f"data:image/jpeg;base64,{base64.b64encode(logo_data).decode()}"
            except Exception:
                # Fallback to file URI if base64 encoding fails
                logo_data_url = logo_path.resolve().as_uri()

        html = render_to_string(
            template_name,
            {
                "invoice": self,
                "for_pdf": True,
                "logo_src": logo_data_url,
            },
        )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page()
                    page.set_viewport_size({"width": 1280, "height": 1920})
                    page.set_content(html, wait_until="networkidle")
                    page.emulate_media(media="screen")
                    pdf_content = page.pdf(
                        format="A4",
                        print_background=True,
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                    )
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise RuntimeError(
                "Playwright could not render the invoice PDF. Ensure Chromium is installed via 'playwright install chromium'."
            ) from exc

        if not self.pdf_file or overwrite:
            self.pdf_file.save(filename, ContentFile(pdf_content), save=True)

    def generate_general_pdf(self, overwrite: bool = True) -> None:
        filename = f"invoice-{self.pk}-general.pdf"
        self._generate_pdf("invoices/detail_pdf.html", filename, overwrite=overwrite)

    def generate_proforma_pdf(self, overwrite: bool = True) -> None:
        filename = f"invoice-{self.pk}-proforma.pdf"
        self._generate_pdf("invoices/detail_pdf_proforma.html", filename, overwrite=overwrite)


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    labour_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f"{self.description} (L:{self.labour_cost} P:{self.parts_cost})"
