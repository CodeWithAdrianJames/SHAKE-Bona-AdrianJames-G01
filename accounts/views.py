from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import BootstrapAuthenticationForm, CustomUserCreationForm


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
    Login view authenticating SHAKE users and displaying clear error feedback
    when credentials are invalid.
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
