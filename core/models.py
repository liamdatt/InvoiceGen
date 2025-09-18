from django.db import models
from django.conf import settings
from django.core.files.base import ContentFile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import io

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
        """
        Programmatically draws the General Invoice onto a blank canvas (no template image),
        pastes the company logo, and renders all fields, items, and totals. Saves as PDF.
        """
        from PIL import Image, ImageDraw, ImageFont  # lazy import

        # Canvas size (A4-ish at ~150-170 DPI). Adjust if you want larger PDFs.
        w, h = 1654, 2339  # approx A4 at 150 dpi
        background_color = "white"
        img = Image.new("RGB", (w, h), color=background_color)
        draw = ImageDraw.Draw(img)

        try:
            font_regular = ImageFont.truetype("DejaVuSans.ttf", 28)
            font_small = ImageFont.truetype("DejaVuSans.ttf", 26)
            font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
        except Exception:
            font_regular = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_bold = ImageFont.load_default()

        # Company logo and header
        left_margin = int(0.08 * w)
        right_margin = int(0.92 * w)
        top_margin = int(0.06 * h)

        # Logo
        logo_path = settings.BASE_DIR / 'invoicegen' / 'resources' / 'logo.jpeg'
        if not logo_path.exists():
            alt = settings.BASE_DIR / 'resources' / 'logo.jpeg'
            if alt.exists():
                logo_path = alt
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                max_logo_w = int(0.28 * w)
                ratio = max_logo_w / logo.width
                logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)))
                img.paste(logo, (left_margin, top_margin), logo if logo.mode == 'RGBA' else None)
            except Exception:
                pass

        # Company text (hard-coded per provided sample)
        header_x = left_margin
        header_y = top_margin + 120
        draw.text((header_x, header_y), "STEPMATH AUTO LIMITED", fill="black", font=font_bold)
        draw.text((header_x, header_y + 36), "(Certified Car Dealer)", fill="black", font=font_regular)
        draw.text((header_x, header_y + 70), "94b Old Hope Road", fill="black", font=font_regular)
        draw.text((header_x, header_y + 104), "Kingston 6", fill="black", font=font_regular)
        draw.text((header_x, header_y + 138), "Tel: (876) 927-8281 / 978-0297", fill="black", font=font_regular)
        draw.text((header_x, header_y + 172), "Email: stepmathauto100@gmail.com", fill="black", font=font_regular)

        # Title
        title = "ESTIMATE FOR REPAIRS"
        tw, th = draw.textbbox((0, 0), title, font=font_bold)[2:]
        draw.text(((w - tw) // 2, top_margin + 40), title, fill="black", font=font_bold)

        # Two-column layout helpers
        left = left_margin
        mid = int(0.58 * w)
        right = int(0.9 * w)

        y0 = int(0.28 * h)
        draw.text((left, y0 + 0), f"Client:  {self.client.name}", fill="black", font=font_regular)
        draw.text((left, y0 + 45), f"Vehicle: {self.vehicle}", fill="black", font=font_regular)
        draw.text((left, y0 + 90), f"Lic#:    {self.lic_no}", fill="black", font=font_regular)
        draw.text((left, y0 + 135), f"Chassis#: {self.chassis_no}", fill="black", font=font_regular)
        date_str = self.date.strftime("%-d-%b-%y") if hasattr(self.date, 'strftime') else str(self.date)
        draw.text((mid + 180, y0 + 0), f"Date: {date_str}", fill="black", font=font_regular)

        # Separator line
        draw.line([(left_margin, y0 + 180), (right_margin, y0 + 180)], fill="#222", width=2)

        # Table headers
        y_items = y0 + 210
        draw.text((left, y_items - 30), "Labour", fill="black", font=font_bold)
        draw.text((right - 120, y_items - 30), "Parts", fill="black", font=font_bold)

        row_h = 36
        for i, item in enumerate(self.items.all()):
            y = y_items + i * row_h
            draw.text((left, y), item.description, fill="black", font=font_small)
            draw.text((mid, y), self._money(item.labour_cost), fill="black", font=font_small)
            draw.text((right, y), self._money(item.parts_cost), fill="black", font=font_small)

        y_totals = max(y_items + (self.items.count() + 1) * row_h + 20, int(0.78 * h))
        draw.text((left, y_totals), "Cost", fill="black", font=font_bold)
        draw.text((mid, y_totals), self._money(self.labour_subtotal), fill="black", font=font_bold)
        draw.text((right, y_totals), self._money(self.parts_subtotal), fill="black", font=font_bold)

        draw.text((left, y_totals + 40), "Plus 15% GCT", fill="black", font=font_bold)
        draw.text((right, y_totals + 40), self._money(self.gct), fill="black", font=font_bold)

        draw.text((left, y_totals + 85), "Total Cost", fill="black", font=font_bold)
        draw.text((right, y_totals + 85), self._money(self.total), fill="black", font=font_bold)

        buf = io.BytesIO()
        img.save(buf, format="PDF", resolution=300)
        buf.seek(0)

        filename = f"invoice-{self.pk}-general.pdf"
        if not self.pdf_file or overwrite:
            self.pdf_file.save(filename, ContentFile(buf.read()), save=True)


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    labour_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f"{self.description} (L:{self.labour_cost} P:{self.parts_cost})"
