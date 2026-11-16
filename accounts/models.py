from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """
    Base custom user model placeholder initialized in Stage 1 so AUTH_USER_MODEL
    is registered before any database migrations are generated.
    Expanded with SHAKE roles and profile fields in Stage 2.
    """
    pass
