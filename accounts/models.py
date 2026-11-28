import secrets

from django.conf import settings
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

    email = models.EmailField(
        "email address",
        max_length=254,
        unique=True,
        error_messages={"unique": "This email address is already in use."},
        help_text="Unique work email address used to sign in to SHAKE (BR-01).",
    )
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
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["ADMIN", "ENCODER"]),
                name="accounts_customuser_role_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        # BR-01: store emails trimmed and lowercased so UNIQUE (email) is
        # effectively case-insensitive and email login lookups stay unambiguous.
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

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


def generate_api_token_key() -> str:
    """Return a cryptographically secure 64-character hex token (F-11)."""
    return secrets.token_hex(32)


class APIToken(models.Model):
    """
    Per-user Bearer token for the localhost loopback REST API (F-11).

    The raw key is shown to its owner once, right after it is generated; the
    profile page afterwards only shows a masked prefix. Revoking a token sets
    `is_active = False` so the row stays as an audit trail.
    """

    DEFAULT_NAME = "Local CLI Token"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=100, default=DEFAULT_NAME)
    key = models.CharField(
        max_length=64,
        unique=True,
        default=generate_api_token_key,
        editable=False,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Local API Token"
        verbose_name_plural = "Local API Tokens"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        state = "active" if self.is_active else "revoked"
        return f"{self.name} ({self.masked_key}, {state})"

    @property
    def masked_key(self) -> str:
        """Return the first 8 characters of the key followed by an ellipsis."""
        return f"{self.key[:8]}…"
