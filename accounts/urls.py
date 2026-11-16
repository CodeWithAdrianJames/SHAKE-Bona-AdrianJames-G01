from django.urls import path

from .views import (
    CustomLoginView,
    CustomLogoutView,
    ProfileDetailView,
    ProfileUpdateView,
    RegisterView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("signup/", RegisterView.as_view(), name="signup"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("profile/", ProfileDetailView.as_view(), name="profile"),
    path("profile/edit/", ProfileUpdateView.as_view(), name="profile_edit"),
]

