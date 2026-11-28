from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from django import forms
from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError

from accounts.forms import BootstrapFormMixin
from contracts.models import CarrierProfile, ContractMetadata, FreightRate

MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


class MultiplePdfInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiplePdfField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            MultiplePdfInput(
                attrs={
                    "accept": ".pdf,application/pdf",
                    "multiple": True,
                }
            ),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            if not data:
                raise forms.ValidationError("Please select at least one contract PDF file.")
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class ContractUploadForm(BootstrapFormMixin, forms.Form):
    """Single or batch digital ocean freight contract PDF upload form."""

    carrier_profile = forms.ChoiceField(
        required=False,
        initial="AUTO",
        label="Carrier template hint",
        help_text=(
            "Auto-detect carrier from PDF header text, or force a specific active carrier profile."
        ),
    )
    pdf_files = MultiplePdfField(
        required=True,
        label="Contract PDF file(s)",
        help_text=(
            "Digital vector-text .pdf files only (max 100 MB per file). "
            "Scanned PDFs and duplicate SHA-256 files are automatically rejected."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("AUTO", "Auto-Detect Carrier from Contract PDF")]
        try:
            carriers = CarrierProfile.objects.filter(is_active=True).order_by(
                "carrier_code"
            )
            choices.extend(
                (c.carrier_code, f"{c.carrier_code} — {c.carrier_name}")
                for c in carriers
            )
        except (OperationalError, ProgrammingError):
            pass
        self.fields["carrier_profile"].choices = choices
        self._apply_bootstrap_classes()

    def clean_pdf_files(self):
        files = self.cleaned_data.get("pdf_files") or []
        if not files:
            raise forms.ValidationError("Please select at least one PDF file to upload.")

        for uploaded_file in files:
            filename = Path(getattr(uploaded_file, "name", "")).name
            if Path(filename).suffix.lower() != ".pdf":
                raise forms.ValidationError(
                    f"Invalid file '{filename}': only .pdf contract files are accepted."
                )
            file_size = getattr(uploaded_file, "size", 0) or 0
            if file_size <= 0:
                raise forms.ValidationError(
                    f"Empty file '{filename}': uploaded PDF must have a positive byte size (BR-08)."
                )
            if file_size > MAX_UPLOAD_SIZE_BYTES:
                raise forms.ValidationError(
                    f"File '{filename}' exceeds the 100 MB maximum upload limit."
                )

        return files


class ContractMetadataForm(BootstrapFormMixin, forms.ModelForm):
    """Update form for extracted contract metadata enforcing BR-10 and BR-11."""

    class Meta:
        model = ContractMetadata
        fields = (
            "contract_number",
            "carrier",
            "trade_scope",
            "commodity_desc",
            "effective_date",
            "expiration_date",
        )
        labels = {
            "contract_number": "Contract number",
            "carrier": "Carrier profile",
            "trade_scope": "Trade scope",
            "commodity_desc": "Commodity description",
            "effective_date": "Effective date",
            "expiration_date": "Expiration date",
        }
        widgets = {
            "contract_number": forms.TextInput(attrs={"placeholder": "e.g., ATL0347N25"}),
            "trade_scope": forms.TextInput(
                attrs={"placeholder": "e.g., NORTH AMERICA - ASIA (WB)"}
            ),
            "commodity_desc": forms.Textarea(attrs={"rows": 3}),
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "expiration_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = CarrierProfile.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.carrier_id:
            qs = CarrierProfile.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.carrier_id)
            )
        self.fields["carrier"].queryset = qs.order_by("carrier_code")
        self.fields["carrier"].empty_label = None
        self._apply_bootstrap_classes()

    def clean_contract_number(self):
        value = (self.cleaned_data.get("contract_number") or "").strip()
        if not value:
            raise forms.ValidationError("Contract number is required.")
        return value

    def clean_trade_scope(self):
        value = (self.cleaned_data.get("trade_scope") or "").strip()
        if not value:
            raise forms.ValidationError("Trade scope is required.")
        return value

    def clean_commodity_desc(self):
        value = (self.cleaned_data.get("commodity_desc") or "").strip()
        if not value:
            raise forms.ValidationError("Commodity description is required.")
        return value

    # BR-10 (expiration_date >= effective_date) is enforced server-side by
    # ContractMetadata.clean(), which ModelForm validation always runs, so the
    # rule holds for this form, the Django admin, and any full_clean() caller.
    # It is not repeated here to avoid reporting the same error twice.


class FreightRateForm(BootstrapFormMixin, forms.ModelForm):
    """Create/update form for normalized FreightRate rows enforcing BR-12 and BR-13."""

    class Meta:
        model = FreightRate
        fields = (
            "origin_port_code",
            "origin_port_name",
            "destination_port_code",
            "destination_port_name",
            "equipment_type",
            "currency_code",
            "rate_amount",
        )
        labels = {
            "origin_port_code": "Origin port code (POL)",
            "origin_port_name": "Origin port name",
            "destination_port_code": "Destination port code (POD)",
            "destination_port_name": "Destination port name",
            "equipment_type": "Equipment type",
            "currency_code": "Currency code",
            "rate_amount": "Base freight rate amount",
        }
        widgets = {
            "origin_port_code": forms.TextInput(
                attrs={"placeholder": "e.g., USCHS", "class": "shake-input-code"}
            ),
            "origin_port_name": forms.TextInput(attrs={"placeholder": "e.g., Charleston"}),
            "destination_port_code": forms.TextInput(
                attrs={"placeholder": "e.g., CNDLC", "class": "shake-input-code"}
            ),
            "destination_port_name": forms.TextInput(attrs={"placeholder": "e.g., Dalian"}),
            "currency_code": forms.TextInput(
                attrs={"placeholder": "USD", "maxlength": "3", "class": "shake-input-code"}
            ),
            "rate_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01", "placeholder": "0.00"}
            ),
        }

    def clean_origin_port_code(self):
        code = (self.cleaned_data.get("origin_port_code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("Origin port code is required.")
        return code

    def clean_destination_port_code(self):
        code = (self.cleaned_data.get("destination_port_code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("Destination port code is required.")
        return code

    def clean_origin_port_name(self):
        name = (self.cleaned_data.get("origin_port_name") or "").strip()
        if not name:
            raise forms.ValidationError("Origin port name is required.")
        return name

    def clean_destination_port_name(self):
        name = (self.cleaned_data.get("destination_port_name") or "").strip()
        if not name:
            raise forms.ValidationError("Destination port name is required.")
        return name

    def clean_currency_code(self):
        code = (self.cleaned_data.get("currency_code") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise forms.ValidationError(
                "Currency code must be a valid 3-letter ISO code (e.g., USD, EUR)."
            )
        return code

    def clean_rate_amount(self):
        amount = self.cleaned_data.get("rate_amount")
        if amount is None or amount <= Decimal("0.00"):
            raise forms.ValidationError(
                "Base freight rate amount must be greater than 0.00 (BR-12)."
            )
        return amount

    # BR-13 (origin_port_code != destination_port_code) is enforced server-side
    # by FreightRate.clean(), which ModelForm validation always runs. Positive
    # rate amounts (BR-12) are also guarded by the model field validator.


class CarrierProfileForm(BootstrapFormMixin, forms.ModelForm):
    """Admin-only form for creating and editing shipping carrier profiles (BR-03)."""

    class Meta:
        model = CarrierProfile
        fields = (
            "carrier_code",
            "carrier_name",
            "template_version",
            "is_active",
        )
        labels = {
            "carrier_code": "Carrier SCAC / code",
            "carrier_name": "Registered carrier name",
            "template_version": "Parser template version",
            "is_active": "Active profile",
        }
        widgets = {
            "carrier_code": forms.TextInput(
                attrs={"placeholder": "e.g., ONE1", "class": "shake-input-code"}
            ),
            "carrier_name": forms.TextInput(
                attrs={"placeholder": "e.g., Ocean Network Express"}
            ),
            "template_version": forms.TextInput(attrs={"placeholder": "e.g., v1.0"}),
        }

    def clean_carrier_code(self):
        code = (self.cleaned_data.get("carrier_code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("Carrier code is required.")
        qs = CarrierProfile.objects.filter(carrier_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Carrier code '{code}' already exists (BR-03)."
            )
        return code

    def clean_carrier_name(self):
        name = (self.cleaned_data.get("carrier_name") or "").strip()
        if not name:
            raise forms.ValidationError("Carrier name is required.")
        qs = CarrierProfile.objects.filter(carrier_name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Carrier name '{name}' is already registered (BR-03)."
            )
        return name

    def clean_template_version(self):
        version = (self.cleaned_data.get("template_version") or "").strip()
        if not version:
            raise forms.ValidationError("Template version is required.")
        return version
