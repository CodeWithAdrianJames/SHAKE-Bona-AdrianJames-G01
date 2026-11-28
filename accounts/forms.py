from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.core.files.uploadedfile import UploadedFile

from .models import APIToken, CustomUser

MAX_PROFILE_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


class BootstrapFormMixin:
    """Apply the appropriate Bootstrap 5 CSS classes to every form widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()

    def _apply_bootstrap_classes(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(
                widget,
                (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple),
            ):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            classes = existing.split()
            if css not in classes:
                classes.append(css)
            widget.attrs["class"] = " ".join(classes)

    def full_clean(self):
        super().full_clean()
        if self.is_bound:
            for name, field in self.fields.items():
                if name in self._errors:
                    existing = field.widget.attrs.get("class", "")
                    classes = existing.split()
                    if "is-invalid" not in classes:
                        classes.append("is-invalid")
                    field.widget.attrs["class"] = " ".join(classes)


class CustomLoginForm(BootstrapFormMixin, AuthenticationForm):
    """
    Bootstrap 5 styled login form authenticating SHAKE users by their unique
    email address (case-insensitive, BR-01) instead of their username.
    """

    email = forms.EmailField(
        max_length=254,
        label="Work Email Address",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "name@logistics-company.com",
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
    )

    field_order = ["email", "password"]

    error_messages = {
        "invalid_login": (
            "Invalid email or password. Please verify your SHAKE credentials and try again."
        ),
        "inactive": "This account is currently inactive. Please contact an Operations Admin.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Email replaces the username credential on the public login form.
        self.fields.pop("username", None)
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        )

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                raise forms.ValidationError(
                    self.error_messages["invalid_login"], code="invalid_login"
                )
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class CustomUserCreationForm(BootstrapFormMixin, UserCreationForm):
    """
    Registration form for SHAKE users.
    Validates required fields, valid email format, case-insensitive unique username
    and email, and matching password confirmation, hashing passwords via UserCreationForm.

    BR-02: public self-registration never exposes a role selector. Every account
    created here is assigned CustomUser.Role.ENCODER server-side; ADMIN accounts
    are provisioned only by an existing administrator (Django admin / createsuperuser).
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="First Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Adrian James"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Last Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Bona"}),
    )
    email = forms.EmailField(
        max_length=254,
        required=True,
        label="Work Email Address",
        widget=forms.EmailInput(
            attrs={"placeholder": "name@logistics-company.com", "autocomplete": "email"}
        ),
    )
    department = forms.CharField(
        max_length=100,
        required=False,
        label="Department",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g., Pricing, Documentation, IT Operations",
                "list": "shake-department-options",
            }
        ),
    )
    contact_number = forms.CharField(
        max_length=30,
        required=False,
        label="Contact Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., +63 917 123 4567"}),
    )

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "department",
            "contact_number",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "Choose a unique username", "autocomplete": "username"}
        )
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "Create a strong password", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Confirm your password", "autocomplete": "new-password"}
        )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("A valid email address is required.")
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean_first_name(self):
        first_name = (self.cleaned_data.get("first_name") or "").strip()
        if not first_name:
            raise forms.ValidationError("First name is required.")
        return first_name

    def clean_last_name(self):
        last_name = (self.cleaned_data.get("last_name") or "").strip()
        if not last_name:
            raise forms.ValidationError("Last name is required.")
        return last_name

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = CustomUser.Role.ENCODER
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserProfileUpdateForm(BootstrapFormMixin, forms.ModelForm):
    """
    Self-service profile update form for authenticated SHAKE users.
    Allows updating personal details, operational department, contact number,
    and profile photo while enforcing required fields and case-insensitive
    email uniqueness (excluding the current user).
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="First Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Adrian James"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Last Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Bona"}),
    )
    email = forms.EmailField(
        max_length=254,
        required=True,
        label="Work Email Address",
        widget=forms.EmailInput(
            attrs={"placeholder": "name@logistics-company.com", "autocomplete": "email"}
        ),
    )
    department = forms.CharField(
        max_length=100,
        required=False,
        label="Department",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g., Pricing, Documentation, IT Operations",
                "list": "shake-department-options",
            }
        ),
    )
    contact_number = forms.CharField(
        max_length=30,
        required=False,
        label="Contact Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., +63 917 123 4567"}),
    )
    profile_photo = forms.ImageField(
        required=False,
        label="Profile Photo",
        help_text="Upload a PNG, JPG, or WEBP avatar image (optional).",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )

    class Meta:
        model = CustomUser
        fields = (
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "department",
            "profile_photo",
        )

    def clean_first_name(self):
        first_name = (self.cleaned_data.get("first_name") or "").strip()
        if not first_name:
            raise forms.ValidationError("First name is required.")
        return first_name

    def clean_last_name(self):
        last_name = (self.cleaned_data.get("last_name") or "").strip()
        if not last_name:
            raise forms.ValidationError("Last name is required.")
        return last_name

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("A valid email address is required.")
        if (
            CustomUser.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError(
                "This email address is already in use by another account."
            )
        return email

    def clean_contact_number(self):
        return (self.cleaned_data.get("contact_number") or "").strip()

    def clean_department(self):
        return (self.cleaned_data.get("department") or "").strip()

    def clean_profile_photo(self):
        # ImageField already verifies the upload is a real image (Pillow); this
        # adds a server-side size cap so the browser `accept` hint is not the only guard.
        photo = self.cleaned_data.get("profile_photo")
        if isinstance(photo, UploadedFile) and photo.size > MAX_PROFILE_PHOTO_BYTES:
            raise forms.ValidationError(
                "Profile photo must be 5 MB or smaller."
            )
        return photo



class CustomPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    """
    Self-service password change form. Requires the current password and
    validates the new password against AUTH_PASSWORD_VALIDATORS.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update(
            {"placeholder": "Enter your current password", "autofocus": True}
        )
        self.fields["new_password1"].widget.attrs.update(
            {"placeholder": "Create a strong new password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"placeholder": "Confirm your new password"}
        )


class APITokenCreateForm(BootstrapFormMixin, forms.Form):
    """Optional label for a new local loopback API token (F-11)."""

    name = forms.CharField(
        max_length=100,
        required=False,
        label="Token Label",
        help_text="Optional. Helps you tell tokens apart, e.g. the script or machine using it.",
        widget=forms.TextInput(attrs={"placeholder": APIToken.DEFAULT_NAME}),
    )

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip() or APIToken.DEFAULT_NAME
