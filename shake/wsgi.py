"""
WSGI config for SHAKE project.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shake.settings')

application = get_wsgi_application()
