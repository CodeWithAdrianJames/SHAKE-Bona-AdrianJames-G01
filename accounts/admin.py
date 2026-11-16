from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "department",
        "is_staff",
        "is_active",
    ]
    list_filter = ["role", "department", "is_staff", "is_superuser", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email", "department"]
    ordering = ["-date_joined"]

    fieldsets = UserAdmin.fieldsets + (
        (
            "SHAKE Operational Profile",
            {
                "fields": (
                    "role",
                    "department",
                    "contact_number",
                    "profile_photo",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "SHAKE Operational Profile",
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "department",
                    "contact_number",
                    "profile_photo",
                )
            },
        ),
    )
