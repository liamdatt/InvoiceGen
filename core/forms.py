from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory

from .models import Client, Invoice, InvoiceItem


INVOICE_SHARED_FIELDS = ("client", "invoice_type", "date", "chassis_no")
INVOICE_GENERAL_FIELDS = ("vehicle", "lic_no")
INVOICE_PROFORMA_FIELDS = (
    "proforma_make",
    "proforma_model",
    "proforma_year",
    "proforma_colour",
    "proforma_cc_rating",
    "proforma_price",
    "proforma_currency",
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "email", "phone", "address"]


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = list(INVOICE_SHARED_FIELDS) + list(INVOICE_GENERAL_FIELDS) + list(INVOICE_PROFORMA_FIELDS)
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "invoice_type": forms.Select(),
            "client": forms.Select(),
            "proforma_year": forms.NumberInput(attrs={"min": 0}),
            "proforma_price": forms.NumberInput(attrs={"step": "0.01", "min": 0}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.widgets.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            existing = field.widget.attrs.get("class", "")
            if css_class not in existing.split():
                field.widget.attrs["class"] = (existing + " " + css_class).strip()

        for name in INVOICE_PROFORMA_FIELDS:
            if name in self.fields:
                self.fields[name].widget.attrs["data-proforma-field"] = "1"

        for name in ("proforma_make", "proforma_model", "proforma_price"):
            if name in self.fields:
                self.fields[name].widget.attrs["data-proforma-required"] = "1"

    def clean(self):
        cleaned_data = super().clean()
        invoice_type = cleaned_data.get("invoice_type")
        if invoice_type == Invoice.Type.PROFORMA:
            required_fields = {
                "proforma_make": "Make",
                "proforma_model": "Model",
                "proforma_price": "Total Cost",
            }
            for field_name, label in required_fields.items():
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, f"{label} is required for proforma invoices.")
        return cleaned_data


ItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    fields=["description", "labour_cost", "parts_cost"],
    extra=1,
    can_delete=True,
)
