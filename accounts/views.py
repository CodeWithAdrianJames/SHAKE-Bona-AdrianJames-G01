from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, UpdateView

from dashboard.views import get_role_dashboard_url

from .forms import (
    APITokenCreateForm,
    CustomLoginForm,
    CustomPasswordChangeForm,
    CustomUserCreationForm,
    UserProfileUpdateForm,
)
from .models import APIToken, CustomUser

# Session key holding a freshly generated API token until the profile page shows it once.
NEW_API_TOKEN_SESSION_KEY = "shake_new_api_token"



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
    Login view authenticating SHAKE users by email address (BR-01), displaying clear error feedback
    when credentials are invalid, and redirecting authenticated users directly
    to their role-specific SHAKE dashboard (/dashboard/admin/ or /dashboard/encoder/).
    """

    authentication_form = CustomLoginForm
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["api_tokens"] = self.request.user.api_tokens.all()
        context["api_token_form"] = APITokenCreateForm()
        # Show a newly generated token exactly once, then drop it from the session.
        context["new_api_token"] = self.request.session.pop(NEW_API_TOKEN_SESSION_KEY, None)
        return context


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



class ProfilePasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """
    Self-service password change (`/accounts/password/`).
    Verifies the current password, applies AUTH_PASSWORD_VALIDATORS, and keeps
    the user signed in by refreshing the session auth hash (handled by
    PasswordChangeView).
    """

    form_class = CustomPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your SHAKE password has been changed successfully.")
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Password could not be changed. Please review and fix the errors below.",
        )
        return super().form_invalid(form)


class APITokenCreateView(LoginRequiredMixin, View):
    """
    POST-only generation of a local loopback API Bearer token (F-11) for the
    signed-in user. The raw key is shown once on the profile page.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        form = APITokenCreateForm(request.POST)
        if not form.is_valid():
            messages.error(request, "API token could not be generated. Please review the token label.")
            return redirect("profile")

        token = APIToken.objects.create(user=request.user, name=form.cleaned_data["name"])
        request.session[NEW_API_TOKEN_SESSION_KEY] = token.key
        messages.success(
            request,
            f"Local API token '{token.name}' generated. Copy it now: it will not be shown again.",
        )
        return redirect(f"{reverse('profile')}#api-tokens")


class APITokenRevokeView(LoginRequiredMixin, View):
    """
    POST-only revocation of one of the signed-in user's own API tokens (F-11).
    Tokens owned by other users resolve to 404 (IDOR protection).
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        token = get_object_or_404(APIToken, pk=pk, user=request.user)
        if token.is_active:
            token.is_active = False
            token.save(update_fields=["is_active"])
            messages.success(request, f"Local API token '{token.name}' ({token.masked_key}) revoked.")
        else:
            messages.info(request, f"Local API token '{token.name}' was already revoked.")
        return redirect(f"{reverse('profile')}#api-tokens")
