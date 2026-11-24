"""
F-01 hardening: enforce UNIQUE (email) (BR-01) and
CHECK (role IN ('ADMIN', 'ENCODER')) (BR-02) on accounts_customuser.

Existing rows are normalized first so the constraints can be applied safely:
  * emails are trimmed and lowercased;
  * blank or duplicate (case-insensitive) emails are replaced with a unique
    placeholder address (the oldest account keeps the original email);
  * any role outside ADMIN / ENCODER is reset to ENCODER (least privilege).
"""

from django.db import migrations, models

PLACEHOLDER_DOMAIN = "users.shake.invalid"
VALID_ROLES = ("ADMIN", "ENCODER")


def normalize_existing_users(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")
    db_alias = schema_editor.connection.alias
    users = list(CustomUser.objects.using(db_alias).order_by("pk"))

    taken = {(user.email or "").strip().lower() for user in users}
    seen = set()

    for user in users:
        original_email = user.email or ""
        original_role = user.role
        email = original_email.strip().lower()

        if not email or email in seen:
            candidate = f"user-{user.pk}@{PLACEHOLDER_DOMAIN}"
            suffix = 1
            while candidate in taken or candidate in seen:
                candidate = f"user-{user.pk}-{suffix}@{PLACEHOLDER_DOMAIN}"
                suffix += 1
            email = candidate
        seen.add(email)

        if user.role not in VALID_ROLES:
            user.role = "ENCODER"

        if email != original_email or user.role != original_role:
            user.email = email
            user.save(update_fields=["email", "role"])


class Migration(migrations.Migration):

    # Run the data fix and the schema changes as separate transactions so
    # PostgreSQL never alters a table that still has pending row updates.
    atomic = False

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            normalize_existing_users,
            reverse_code=migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AlterField(
            model_name="customuser",
            name="email",
            field=models.EmailField(
                error_messages={"unique": "This email address is already in use."},
                help_text="Unique work email address used to sign in to SHAKE (BR-01).",
                max_length=254,
                unique=True,
                verbose_name="email address",
            ),
        ),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.CheckConstraint(
                condition=models.Q(role__in=["ADMIN", "ENCODER"]),
                name="accounts_customuser_role_valid",
            ),
        ),
    ]
