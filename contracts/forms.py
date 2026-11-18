from __future__ import annotations

from pathlib import Path

from django import forms
from django.db.utils import OperationalError, ProgrammingError

from accounts.forms import BootstrapFormMixin
from contracts.models import CarrierProfile

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
        label="Carrier Template Hint",
        help_text=(
            "Auto-detect carrier from PDF header text, or force a specific active carrier profile."
        ),
    )
    pdf_files = MultiplePdfField(
        required=True,
        label="Contract PDF File(s)",
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
