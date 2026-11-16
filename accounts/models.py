from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class CustomUserManager(UserManager):
    """Custom manager for CustomUser ensuring superusers default to the ADMIN role."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", CustomUser.Role.ADMIN)
        return super().create_superuser(username, email=email, password=password, **extra_fields)


class CustomUser(AbstractUser):
    """
    Custom User model for SHAKE (Structured Handling and Automated Knowledge Extraction).
    Supports role-based access control between Operations Admins and Freight Analysts / Encoders.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Operations Admin"
        ENCODER = "ENCODER", "Freight Analyst / Encoder"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ENCODER,
        help_text="Designates the user's operational workspace role in SHAKE.",
    )
    contact_number = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Contact phone number for operational notifications.",
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Operational department (e.g., Pricing, Documentation, IT Operations).",
    )
    profile_photo = models.ImageField(
        upload_to="profile_photos/",
        blank=True,
        null=True,
        help_text="Optional profile avatar image.",
    )

    objects = CustomUserManager()

    class Meta:
        verbose_name = "SHAKE User"
        verbose_name_plural = "SHAKE Users"
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_admin_role(self) -> bool:
        """Return True if the user holds the Operations Admin role."""
        return self.role == self.Role.ADMIN

    @property
    def is_encoder_role(self) -> bool:
        """Return True if the user holds the Freight Analyst / Encoder role."""
        return self.role == self.Role.ENCODER

    @property
    def full_name_or_username(self) -> str:
        """Return the user's full name if set, falling back to username."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.username

    @property
    def initials(self) -> str:
        """Return 1-2 uppercase initials for the default avatar fallback."""
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        if self.first_name:
            return self.first_name[:2].upper()
        return self.username[:2].upper() if self.username else "SH"
