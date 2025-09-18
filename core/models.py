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

        # Helpers
        def text_width(value: str, font) -> int:
            if not value:
                return 0
            bbox = draw.textbbox((0, 0), value, font=font)
            return bbox[2] - bbox[0]

        def draw_right(value: str, x_right: int, y: int, font, fill="black") -> None:
            if not value:
                return
            draw.text((x_right - text_width(value, font), y), value, font=font, fill=fill)

        def wrap_lines(value: str, max_width: int, font) -> list[str]:
            if not value:
                return [""]
            words = value.split()
            if not words:
                return [value.strip() or ""]
            lines: list[str] = []
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}" if current else word
                if text_width(candidate, font) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
            return lines or [""]

        # Company logo and header
        left_margin = int(0.08 * w)
        right_margin = w - left_margin
        top_margin = int(0.06 * h)
        content_width = right_margin - left_margin

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
        draw.text(
            (left_margin + (content_width - text_width(title, font_bold)) // 2, top_margin + 36),
            title,
            fill="black",
            font=font_bold,
        )

        # Metadata block
        meta_top = header_y + 220
        meta_line_height = 42
        date_str = self.date.strftime("%-d-%b-%y") if hasattr(self.date, 'strftime') else str(self.date)
        meta_left_labels = [
            ("Client:", self.client.name),
            ("Vehicle:", self.vehicle or ""),
            ("Lic#:", self.lic_no or ""),
            ("Chassis#:", self.chassis_no or ""),
        ]
        for index, (label, value) in enumerate(meta_left_labels):
            y = meta_top + index * meta_line_height
            draw.text((left_margin, y), f"{label}  {value}", fill="black", font=font_regular)
        draw_right(f"Date: {date_str}", right_margin, meta_top, font_regular)

        separator_y = meta_top + meta_line_height * 4 + 20
        draw.line([(left_margin, separator_y), (right_margin, separator_y)], fill="#1f2937", width=2)

        # Items table
        table_top = separator_y + 36
        table_left = left_margin
        table_right = right_margin
        header_height = 60
        desc_col_width = int(content_width * 0.55)
        labour_col_width = int(content_width * 0.2)
        parts_col_width = content_width - desc_col_width - labour_col_width
        labour_col_left = table_left + desc_col_width
        parts_col_left = labour_col_left + labour_col_width
        desc_text_x = table_left + 24
        labour_right = parts_col_left - 24
        parts_right = table_right - 24

        draw.rounded_rectangle(
            [(table_left, table_top), (table_right, table_top + header_height)],
            radius=18,
            fill="#f1f5f9",
            outline="#d0d5dd",
        )
        draw.text((desc_text_x, table_top + 18), "Description", fill="#0f172a", font=font_bold)
        draw_right("Labour", labour_right, table_top + 18, font_bold, fill="#0f172a")
        draw_right("Parts", parts_right, table_top + 18, font_bold, fill="#0f172a")

        items = list(self.items.all())
        body_top = table_top + header_height + 12
        line_height = 36
        current_y = body_top

        if items:
            for item in items:
                desc_lines = wrap_lines(item.description, desc_col_width - 32, font_small)
                row_height = max(line_height * len(desc_lines), line_height)
                for idx, line in enumerate(desc_lines):
                    draw.text((desc_text_x, current_y + idx * line_height), line, fill="black", font=font_small)
                draw_right(self._money(item.labour_cost), labour_right, current_y, font_small)
                draw_right(self._money(item.parts_cost), parts_right, current_y, font_small)
                row_bottom = current_y + row_height
                draw.line([(table_left, row_bottom + 8), (table_right, row_bottom + 8)], fill="#e2e8f0", width=2)
                current_y = row_bottom + 24
        else:
            draw.text((desc_text_x, current_y), "No invoice items have been added yet.", fill="#475569", font=font_small)
            current_y += line_height + 24

        table_bottom = max(current_y - 24, table_top + header_height)
        draw.line([(labour_col_left, table_top), (labour_col_left, table_bottom)], fill="#d8dee9", width=2)
        draw.line([(parts_col_left, table_top), (parts_col_left, table_bottom)], fill="#d8dee9", width=2)

        totals_top = current_y + 12
        totals_rows = [
            ("Cost", self._money(self.labour_subtotal), self._money(self.parts_subtotal)),
            ("Plus 15% GCT", "", self._money(self.gct)),
            ("Total Cost", "", self._money(self.total)),
        ]
        totals_line_height = 48
        for label, labour_value, parts_value in totals_rows:
            draw.text((labour_col_left - 36, totals_top), label, fill="black", font=font_bold)
            if labour_value:
                draw_right(labour_value, labour_right, totals_top, font_bold)
            draw_right(parts_value, parts_right, totals_top, font_bold)
            totals_top += totals_line_height

        # Signature block
        signature_line_y = max(totals_top + 60, h - int(0.16 * h))
        draw.line([(left_margin, signature_line_y), (left_margin + 320, signature_line_y)], fill="#111111", width=3)
        draw.text((left_margin, signature_line_y + 18), "ERROL DUHANEY", fill="black", font=font_bold)
        draw.text((left_margin, signature_line_y + 52), "MANAGING DIRECTOR", fill="black", font=font_regular)

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
