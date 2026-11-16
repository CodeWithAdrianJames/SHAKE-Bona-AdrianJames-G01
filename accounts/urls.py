from django.urls import path

from .views import CustomLoginView, CustomLogoutView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("signup/", RegisterView.as_view(), name="signup"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
]
