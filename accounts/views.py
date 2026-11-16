from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, UpdateView

from dashboard.views import get_role_dashboard_url

from .forms import (
    BootstrapAuthenticationForm,
    CustomUserCreationForm,
    UserProfileUpdateForm,
)
from .models import CustomUser



class RegisterView(CreateView):
    """
    Account registration view for SHAKE.
    Validates inputs via CustomUserCreationForm, hashes the password, and redirects
    to the login page with a Bootstrap success alert.
    """

    form_class = CustomUserCreationForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Account created successfully! Please log in to access your SHAKE workspace.",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Registration could not be completed. Please review and fix the errors below.",
        )
        return super().form_invalid(form)


# Alias matching the reference project naming convention
SignUpView = RegisterView


class CustomLoginView(LoginView):
    """
    Login view authenticating SHAKE users, displaying clear error feedback
    when credentials are invalid, and redirecting authenticated users directly
    to their role-specific SHAKE dashboard (/dashboard/admin/ or /dashboard/encoder/).
    """

    authentication_form = BootstrapAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        messages.success(
            self.request,
            f"Welcome back, {user.full_name_or_username}! Signed in as {user.get_role_display()}.",
        )
        return super().form_valid(form)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        generic_roots = {reverse("dashboard"), reverse("dashboard_root")}
        if redirect_to and redirect_to not in generic_roots:
            return redirect_to
        return get_role_dashboard_url(self.request.user)


class CustomLogoutView(LogoutView):
    """
    POST-only Logout view for CSRF safety. Terminates the user session and
    redirects to the login page with a confirmation message.
    """

    http_method_names = ["post", "options"]
    next_page = reverse_lazy("login")

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(
            request,
            "You have been securely logged out of your SHAKE session.",
        )
        return response


class ProfileDetailView(LoginRequiredMixin, DetailView):
    """
    Self-only Profile Detail View (`/accounts/profile/`).
    Always resolves `get_object()` from `self.request.user` to prevent IDOR
    and ensure users can only view their own profile.
    """

    model = CustomUser
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_object(self, queryset=None):
        return self.request.user


ProfileView = ProfileDetailView


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """
    Self-only Profile Update View (`/accounts/profile/edit/`).
    Always resolves `get_object()` from `self.request.user` to prevent IDOR
    and allows the logged-in user to update their profile details and photo.
    """

    model = CustomUser
    form_class = UserProfileUpdateForm
    template_name = "accounts/profile_edit.html"
    context_object_name = "profile_user"
    success_url = reverse_lazy("profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Your SHAKE profile has been updated successfully.",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Profile update could not be saved. Please review and fix the errors below.",
        )
        return super().form_invalid(form)


ProfileEditView = ProfileUpdateView

