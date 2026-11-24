from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """
    Authenticate SHAKE users by their unique email address (BR-01).

    The lookup is case-insensitive. Calls that pass ``username`` instead of
    ``email`` (Django admin site, ``Client.login(username=...)``) fall back to
    the standard ModelBackend behaviour.
    """

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        if email is None:
            return super().authenticate(
                request, username=username, password=password, **kwargs
            )
        if password is None:
            return None

        UserModel = get_user_model()
        email = email.strip()
        try:
            user = UserModel._default_manager.get(email__iexact=email)
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user.
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
