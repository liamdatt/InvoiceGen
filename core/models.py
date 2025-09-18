from django.db import models
from django.conf import settings
from django.core.files.base import ContentFile
from decimal import Decimal, ROUND_HALF_UP
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
        from PIL import Image, ImageDraw, ImageFont  # lazy import

        def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                return ImageFont.load_default()

        def right_align(x: int, y: int, text: str, font: ImageFont.FreeTypeFont, fill: str = "black") -> None:
            bbox = draw.textbbox((0, 0), text, font=font)
            draw.text((x - (bbox[2] - bbox[0]), y), text, font=font, fill=fill)

        def wrap_description(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
            words = text.split()
            lines: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                bbox = draw.textbbox((0, 0), candidate, font=font)
                if bbox[2] - bbox[0] <= max_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            return lines or [""]

        page_w, page_h = 1654, 2339  # approx A4 at 150 dpi
        background = Image.new("RGB", (page_w, page_h), color="#f8fafc")
        draw = ImageDraw.Draw(background)

        font_title = load_font("DejaVuSerif-Bold.ttf", 64)
        font_heading = load_font("DejaVuSerif-Bold.ttf", 40)
        font_body = load_font("DejaVuSerif.ttf", 34)
        font_small = load_font("DejaVuSerif.ttf", 30)
        font_caption = load_font("DejaVuSerif.ttf", 28)

        outer_margin_x = int(0.06 * page_w)
        outer_margin_y = int(0.05 * page_h)
        card_radius = 28
        card_bbox = (
            outer_margin_x,
            outer_margin_y,
            page_w - outer_margin_x,
            page_h - outer_margin_y,
        )
        draw.rounded_rectangle(card_bbox, radius=card_radius, fill="white", outline="#d0d7e2", width=4)

        content_left = outer_margin_x + 80
        content_right = page_w - outer_margin_x - 80
        content_width = content_right - content_left
        cursor_y = outer_margin_y + 120

        # Logo and brand block
        logo_path = settings.BASE_DIR / 'invoicegen' / 'resources' / 'logo.jpeg'
        if not logo_path.exists():
            alt = settings.BASE_DIR / 'resources' / 'logo.jpeg'
            if alt.exists():
                logo_path = alt

        logo_max_width = int(content_width * 0.22)
        brand_gap = 40
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                ratio = min(logo_max_width / logo.width, 1.0)
                logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)))
                background.paste(logo, (content_left, cursor_y), logo if logo.mode == 'RGBA' else None)
                text_x = content_left + logo.width + brand_gap
            except Exception:
                text_x = content_left
        else:
            text_x = content_left

        brand_lines = [
            ("STEPMATH AUTO LIMITED", font_heading),
            ("(Certified Car Dealer)", font_caption),
            ("94b Old Hope Road", font_body),
            ("Kingston 6", font_body),
            ("Tel: (876) 927-8281 / 978-0297", font_body),
            ("Email: stepmathauto100@gmail.com", font_body),
        ]
        text_y = cursor_y
        for text, font in brand_lines:
            draw.text((text_x, text_y), text, font=font, fill="#111111")
            text_y += font.size + 6

        cursor_y = max(text_y, cursor_y + 240)

        title_text = "ESTIMATE FOR REPAIRS"
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        draw.text(
            ((page_w - (title_bbox[2] - title_bbox[0])) // 2, cursor_y),
            title_text,
            font=font_title,
            fill="#111111",
        )

        cursor_y += font_title.size + 50
        draw.line([(content_left, cursor_y), (content_right, cursor_y)], fill="#111111", width=3)
        cursor_y += 40

        meta_left = content_left
        meta_right = content_right
        meta_top = cursor_y
        meta_rows = [
            ("Client", self.client.name),
            ("Vehicle", self.vehicle or ""),
            ("Lic#", self.lic_no or ""),
            ("Chassis#", self.chassis_no or ""),
        ]
        for label, value in meta_rows:
            draw.text((meta_left, cursor_y), f"{label}:", font=font_heading, fill="#111111")
            draw.text((meta_left + 200, cursor_y), value, font=font_body, fill="#111111")
            cursor_y += font_body.size + 12

        date_str = self.date.strftime("%-d-%b-%y") if hasattr(self.date, 'strftime') else str(self.date)
        right_align(meta_right, meta_top, f"Date: {date_str}", font=font_body)

        cursor_y += 10
        draw.line([(content_left, cursor_y), (content_right, cursor_y)], fill="#d0d7e2", width=2)
        cursor_y += 40

        table_header_height = 60
        description_width = int(content_width * 0.55)
        labour_col_right = content_left + description_width + int(content_width * 0.22)
        parts_col_right = content_right

        header_bbox = (content_left, cursor_y, content_right, cursor_y + table_header_height)
        draw.rectangle(header_bbox, fill="#e2e8f0")
        draw.text((content_left + 20, cursor_y + 12), "Description", font=font_heading, fill="#111111")
        right_align(parts_col_right, cursor_y + 12, "Parts Cost", font=font_heading)
        right_align(labour_col_right, cursor_y + 12, "Labour Cost", font=font_heading)

        cursor_y += table_header_height + 10

        row_y = cursor_y
        items_qs = list(self.items.all())
        for item in items_qs:
            desc_lines = wrap_description(item.description, font_small, description_width - 40)
            line_height = font_small.size + 10
            row_height = max(line_height * len(desc_lines), line_height)

            # row separator
            draw.line([(content_left, row_y + row_height + 10), (content_right, row_y + row_height + 10)], fill="#e2e8f0", width=2)

            text_y_line = row_y
            for line in desc_lines:
                draw.text((content_left + 20, text_y_line), line, font=font_small, fill="#111111")
                text_y_line += line_height

            right_align(labour_col_right, row_y + 5, self._money(item.labour_cost), font=font_small)
            right_align(parts_col_right, row_y + 5, self._money(item.parts_cost), font=font_small)

            row_y += row_height + 20

        if not items_qs:
            draw.text((content_left + 20, row_y), "No invoice items have been added yet.", font=font_small, fill="#111111")
            row_y += font_small.size + 20

        cursor_y = row_y + 20

        totals_label_x = content_left + description_width - 40
        totals = [
            ("Cost", self._money(self.labour_subtotal), self._money(self.parts_subtotal)),
            ("Plus 15% GCT", "", self._money(self.gct)),
            ("Total Cost", "", self._money(self.total)),
        ]

        for label, labour_val, parts_val in totals:
            draw.text((totals_label_x, cursor_y), label, font=font_heading, fill="#111111")
            if labour_val:
                right_align(labour_col_right, cursor_y, labour_val, font=font_heading)
            if parts_val:
                right_align(parts_col_right, cursor_y, parts_val, font=font_heading)
            cursor_y += font_heading.size + 24

        cursor_y += 60
        draw.line([(content_left, cursor_y), (content_left + 320, cursor_y)], fill="#111111", width=3)
        cursor_y += 20
        draw.text((content_left, cursor_y), "ERROL DUHANEY", font=font_heading, fill="#111111")
        cursor_y += font_heading.size + 6
        draw.text((content_left, cursor_y), "MANAGING DIRECTOR", font=font_body, fill="#111111")

        buf = io.BytesIO()
        background.save(buf, format="PDF", resolution=300)
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
