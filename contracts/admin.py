from django.contrib import admin

from .models import (
    ArbitraryCharge,
    BatchUpload,
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    ExportRecord,
    FreightRate,
    ProcessingJob,
)


@admin.register(CarrierProfile)
class CarrierProfileAdmin(admin.ModelAdmin):
    list_display = ("carrier_code", "carrier_name", "template_version", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("carrier_code", "carrier_name")


@admin.register(BatchUpload)
class BatchUploadAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "user", "total_files", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("batch_number", "user__username")


@admin.register(DocumentFile)
class DocumentFileAdmin(admin.ModelAdmin):
    list_display = ("original_file_name", "batch", "page_count", "file_size_bytes", "status", "uploaded_at")
    list_filter = ("status",)
    search_fields = ("original_file_name", "file_hash_sha256")


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "document", "job_type", "status", "started_at", "completed_at")
    list_filter = ("job_type", "status")


@admin.register(ContractMetadata)
class ContractMetadataAdmin(admin.ModelAdmin):
    list_display = ("contract_number", "carrier", "trade_scope", "effective_date", "expiration_date", "extracted_at")
    list_filter = ("carrier",)
    search_fields = ("contract_number", "trade_scope", "commodity_desc")


@admin.register(FreightRate)
class FreightRateAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "line_item_sequence",
        "origin_port_code",
        "destination_port_code",
        "equipment_type",
        "currency_code",
        "rate_amount",
    )
    list_filter = ("equipment_type", "currency_code")
    search_fields = ("origin_port_code", "origin_port_name", "destination_port_code", "destination_port_name")


@admin.register(ArbitraryCharge)
class ArbitraryChargeAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "line_item_sequence",
        "charge_type",
        "location_code",
        "via_gateway_port",
        "equipment_type",
        "charge_amount",
        "transport_mode",
    )
    list_filter = ("charge_type", "equipment_type", "transport_mode")


@admin.register(ExportRecord)
class ExportRecordAdmin(admin.ModelAdmin):
    list_display = ("contract", "export_format", "user", "file_path", "exported_at")
    list_filter = ("export_format",)
