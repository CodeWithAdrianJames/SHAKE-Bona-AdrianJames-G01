from django.db import migrations


DEFAULT_CARRIERS = [
    ("MSCU", "Mediterranean Shipping Company", "v1.0"),
    ("CMDU", "CMA CGM", "v1.0"),
    ("COSU", "COSCO SHIPPING", "v1.0"),
    ("MAEU", "Maersk", "v1.0"),
    ("UNKN", "General / Unassigned Carrier", "v1.0"),
]


def seed_default_carriers(apps, schema_editor):
    CarrierProfile = apps.get_model("contracts", "CarrierProfile")
    for code, name, version in DEFAULT_CARRIERS:
        CarrierProfile.objects.get_or_create(
            carrier_code=code,
            defaults={
                "carrier_name": name,
                "template_version": version,
                "is_active": True,
            },
        )


def unseed_default_carriers(apps, schema_editor):
    CarrierProfile = apps.get_model("contracts", "CarrierProfile")
    CarrierProfile.objects.filter(
        carrier_code__in=[code for code, _, _ in DEFAULT_CARRIERS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_carriers, reverse_code=unseed_default_carriers),
    ]
