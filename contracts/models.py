from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

# Field-level validators mirror the database CHECK constraints so ModelForms,
# the Django admin, and full_clean() reject bad values with a clear message
# before the database raises an IntegrityError (PD3 hardening).
POSITIVE_AMOUNT_VALIDATORS = [
    MinValueValidator(
        Decimal("0.01"),
        message="Base freight rate amount must be greater than 0.00 (BR-12).",
    ),
]
NON_NEGATIVE_AMOUNT_VALIDATORS = [
    MinValueValidator(Decimal("0.00"), message="Charge amount cannot be negative."),
]
CONFIDENCE_SCORE_VALIDATORS = [
    MinValueValidator(Decimal("0.000"), message="Confidence score must be between 0.000 and 1.000."),
    MaxValueValidator(Decimal("1.000"), message="Confidence score must be between 0.000 and 1.000."),
]
PAGE_NUMBER_VALIDATORS = [
    MinValueValidator(1, message="Page numbers start at 1."),
]


class EquipmentType(models.TextChoices):
    """Standard ISO maritime container equipment codes (BR-13)."""

    GP20 = "20GP", "20GP"
    GP40 = "40GP", "40GP"
    HC40 = "40HC", "40HC"
    HC45 = "45HC", "45HC"
    RF20 = "20RF", "20RF"
    RF40 = "40RF", "40RF"
    SPECIAL = "SPECIAL", "SPECIAL"


class CarrierProfile(models.Model):
    """Registry of supported ocean freight shipping lines (BR-03)."""

    carrier_id = models.BigAutoField(primary_key=True)
    carrier_code = models.CharField(max_length=10, unique=True)
    carrier_name = models.CharField(max_length=100, unique=True)
    template_version = models.CharField(max_length=20, default="v1.0")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "carrier_profiles"
        ordering = ["carrier_code"]
        verbose_name = "Carrier Profile"
        verbose_name_plural = "Carrier Profiles"

    def __str__(self) -> str:
        return f"{self.carrier_code} — {self.carrier_name}"


class BatchUpload(models.Model):
    """Logical PDF ingestion batch owned by an authenticated user (BR-04, BR-05)."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    batch_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name="batch_uploads",
    )
    batch_number = models.CharField(max_length=50, unique=True)
    total_files = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "batch_uploads"
        ordering = ["-created_at"]
        verbose_name = "Batch Upload"
        verbose_name_plural = "Batch Uploads"
        constraints = [
            models.CheckConstraint(
                condition=Q(total_files__gte=1),
                name="chk_batch_total_files_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "QUEUED",
                        "PROCESSING",
                        "COMPLETED",
                        "FAILED",
                        "CANCELLED",
                    ]
                ),
                name="chk_batch_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch_number} ({self.get_status_display()})"


class DocumentFile(models.Model):
    """Physical uploaded PDF document tracked via SHA-256 checksum (BR-06, BR-07, BR-08, BR-09)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARSING = "PARSING", "Parsing"
        STITCHING = "STITCHING", "Stitching"
        EXTRACTED = "EXTRACTED", "Extracted"
        FAILED = "FAILED", "Failed"
        ARCHIVED = "ARCHIVED", "Archived"

    document_id = models.BigAutoField(primary_key=True)
    batch = models.ForeignKey(
        BatchUpload,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    uploaded_file = models.FileField(upload_to="contracts/pdfs/%Y/%m/")
    original_file_name = models.CharField(max_length=255)
    file_hash_sha256 = models.CharField(max_length=64, unique=True)
    file_size_bytes = models.BigIntegerField()
    page_count = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_files"
        ordering = ["-uploaded_at"]
        verbose_name = "Document File"
        verbose_name_plural = "Document Files"
        constraints = [
            models.CheckConstraint(
                condition=Q(file_size_bytes__gt=0),
                name="chk_document_file_size_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(page_count__gt=0),
                name="chk_document_page_count_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "PENDING",
                        "PARSING",
                        "STITCHING",
                        "EXTRACTED",
                        "FAILED",
                        "ARCHIVED",
                    ]
                ),
                name="chk_document_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.original_file_name} [{self.status}]"


class ProcessingJob(models.Model):
    """Execution audit trail for offline PDF parsing & extraction runs."""

    class JobType(models.TextChoices):
        PARSE_VECTOR = "PARSE_VECTOR", "Parse Vector Layout"
        STITCH_TABLES = "STITCH_TABLES", "Stitch Cross-Page Tables"
        EXTRACT_ENTITIES = "EXTRACT_ENTITIES", "Extract Contract Entities"
        FULL_PIPELINE = "FULL_PIPELINE", "Full Extraction Pipeline"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    job_id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(
        DocumentFile,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    job_type = models.CharField(
        max_length=30,
        choices=JobType.choices,
        default=JobType.FULL_PIPELINE,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    error_message = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "processing_jobs"
        ordering = ["-started_at"]
        verbose_name = "Processing Job"
        verbose_name_plural = "Processing Jobs"
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    job_type__in=[
                        "PARSE_VECTOR",
                        "STITCH_TABLES",
                        "EXTRACT_ENTITIES",
                        "FULL_PIPELINE",
                    ]
                ),
                name="chk_processing_job_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["RUNNING", "COMPLETED", "FAILED"]),
                name="chk_processing_job_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Job #{self.job_id} ({self.job_type}: {self.status})"


class ContractMetadata(models.Model):
    """1:1 extracted contract header context linked to a DocumentFile (BR-09, BR-10, BR-11)."""

    contract_id = models.BigAutoField(primary_key=True)
    document = models.OneToOneField(
        DocumentFile,
        on_delete=models.RESTRICT,
        related_name="contract_metadata",
    )
    carrier = models.ForeignKey(
        CarrierProfile,
        on_delete=models.RESTRICT,
        related_name="contracts",
    )
    contract_number = models.CharField(max_length=100)
    trade_scope = models.CharField(max_length=255)
    commodity_desc = models.TextField()
    effective_date = models.DateField()
    expiration_date = models.DateField()
    extracted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contract_metadata"
        ordering = ["-extracted_at"]
        verbose_name = "Contract Metadata"
        verbose_name_plural = "Contract Metadata"
        constraints = [
            models.CheckConstraint(
                condition=Q(expiration_date__gte=F("effective_date")),
                name="chk_contract_dates_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.effective_date
            and self.expiration_date
            and self.expiration_date < self.effective_date
        ):
            raise ValidationError(
                {
                    "expiration_date": (
                        "Expiration date must be on or after the effective date (BR-10)."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.contract_number} ({self.carrier.carrier_code})"


class FreightRate(models.Model):
    """Normalized base ocean freight rate row (BR-12, BR-13)."""

    rate_id = models.BigAutoField(primary_key=True)
    contract = models.ForeignKey(
        ContractMetadata,
        on_delete=models.CASCADE,
        related_name="freight_rates",
    )
    line_item_sequence = models.PositiveIntegerField()
    origin_port_code = models.CharField(max_length=10)
    origin_port_name = models.CharField(max_length=100)
    destination_port_code = models.CharField(max_length=10)
    destination_port_name = models.CharField(max_length=100)
    equipment_type = models.CharField(
        max_length=15,
        choices=EquipmentType.choices,
    )
    currency_code = models.CharField(max_length=3, default="USD")
    rate_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=POSITIVE_AMOUNT_VALIDATORS,
    )
    source_page_start = models.PositiveIntegerField(
        default=1, validators=PAGE_NUMBER_VALIDATORS
    )
    source_page_end = models.PositiveIntegerField(
        default=1, validators=PAGE_NUMBER_VALIDATORS
    )
    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.950"),
        validators=CONFIDENCE_SCORE_VALIDATORS,
    )

    class Meta:
        db_table = "freight_rates"
        ordering = ["line_item_sequence"]
        verbose_name = "Freight Rate"
        verbose_name_plural = "Freight Rates"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "line_item_sequence"],
                name="uq_contract_rate_seq",
            ),
            models.CheckConstraint(
                condition=Q(rate_amount__gt=Decimal("0.00")),
                name="chk_freight_rate_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    equipment_type__in=[
                        "20GP",
                        "40GP",
                        "40HC",
                        "45HC",
                        "20RF",
                        "40RF",
                        "SPECIAL",
                    ]
                ),
                name="chk_freight_rate_equipment_valid",
            ),
            models.CheckConstraint(
                condition=~Q(origin_port_code=F("destination_port_code")),
                name="chk_freight_rate_ports_distinct",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        origin = (self.origin_port_code or "").strip().upper()
        destination = (self.destination_port_code or "").strip().upper()
        if origin and destination and origin == destination:
            errors["destination_port_code"] = (
                "Destination port code must differ from origin port code (BR-13)."
            )
        if (
            self.source_page_start
            and self.source_page_end
            and self.source_page_end < self.source_page_start
        ):
            errors["source_page_end"] = (
                "Source end page must be on or after the source start page."
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return (
            f"{self.contract.contract_number} #{self.line_item_sequence}: "
            f"{self.origin_port_code}->{self.destination_port_code} "
            f"{self.equipment_type} {self.currency_code} {self.rate_amount}"
        )


class ArbitraryCharge(models.Model):
    """Normalized origin or destination inland arbitrary surcharge row (BR-13)."""

    class ChargeType(models.TextChoices):
        ORIGIN = "ORIGIN", "Origin Arbitrary"
        DESTINATION = "DESTINATION", "Destination Arbitrary"

    class TransportMode(models.TextChoices):
        RAIL = "RAIL", "Rail"
        TRUCK = "TRUCK", "Truck"
        BARGE = "BARGE", "Barge"
        FEEDER = "FEEDER", "Feeder"
        INTERMODAL = "INTERMODAL", "Intermodal"

    charge_id = models.BigAutoField(primary_key=True)
    contract = models.ForeignKey(
        ContractMetadata,
        on_delete=models.CASCADE,
        related_name="arbitrary_charges",
    )
    line_item_sequence = models.PositiveIntegerField()
    charge_type = models.CharField(
        max_length=15,
        choices=ChargeType.choices,
    )
    location_code = models.CharField(max_length=10)
    location_name = models.CharField(max_length=100)
    via_gateway_port = models.CharField(max_length=100)
    equipment_type = models.CharField(
        max_length=15,
        choices=EquipmentType.choices,
    )
    currency_code = models.CharField(max_length=3, default="USD")
    charge_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=NON_NEGATIVE_AMOUNT_VALIDATORS,
    )
    transport_mode = models.CharField(
        max_length=20,
        choices=TransportMode.choices,
        default=TransportMode.INTERMODAL,
    )
    source_page_num = models.PositiveIntegerField(
        default=1, validators=PAGE_NUMBER_VALIDATORS
    )
    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.950"),
        validators=CONFIDENCE_SCORE_VALIDATORS,
    )

    class Meta:
        db_table = "arbitrary_charges"
        ordering = ["line_item_sequence"]
        verbose_name = "Arbitrary Charge"
        verbose_name_plural = "Arbitrary Charges"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "line_item_sequence"],
                name="uq_contract_arb_seq",
            ),
            models.CheckConstraint(
                condition=Q(charge_amount__gte=Decimal("0.00")),
                name="chk_arb_charge_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(charge_type__in=["ORIGIN", "DESTINATION"]),
                name="chk_arb_charge_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    equipment_type__in=[
                        "20GP",
                        "40GP",
                        "40HC",
                        "45HC",
                        "20RF",
                        "40RF",
                        "SPECIAL",
                    ]
                ),
                name="chk_arb_equipment_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    transport_mode__in=[
                        "RAIL",
                        "TRUCK",
                        "BARGE",
                        "FEEDER",
                        "INTERMODAL",
                    ]
                ),
                name="chk_arb_transport_mode_valid",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.contract.contract_number} [{self.charge_type}] "
            f"{self.location_code} via {self.via_gateway_port} ({self.equipment_type})"
        )


class ExportRecord(models.Model):
    """Audit log entry for JSON, XLSX, and CSV contract downloads."""

    class ExportFormat(models.TextChoices):
        JSON = "JSON", "JSON"
        XLSX = "XLSX", "Excel (.xlsx)"
        CSV = "CSV", "CSV"

    export_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name="export_records",
    )
    # RESTRICT (PD3 hardening): the export audit trail is immutable, so a
    # contract with export history can never be hard-deleted (pairs with BR-09).
    contract = models.ForeignKey(
        ContractMetadata,
        on_delete=models.RESTRICT,
        related_name="export_records",
    )
    export_format = models.CharField(
        max_length=10,
        choices=ExportFormat.choices,
    )
    file_path = models.CharField(max_length=255)
    exported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "export_records"
        ordering = ["-exported_at"]
        verbose_name = "Export Record"
        verbose_name_plural = "Export Records"
        constraints = [
            models.CheckConstraint(
                condition=Q(export_format__in=["JSON", "XLSX", "CSV"]),
                name="chk_export_format_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contract.contract_number} -> {self.export_format} by {self.user}"
