"""
URL configuration for SHAKE project.

Custom error pages: Django's default handlers render `templates/404.html`
(with request context) and `templates/500.html` (with an empty context and no
context processors) whenever DEBUG is False.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('contracts/', include('contracts.urls')),
    path('api/v1/', include('contracts.api_urls')),
    path('', include('dashboard.urls')),
]

if settings.DEBUG:
    # Serve only profile avatars from MEDIA_ROOT during development. Uploaded
    # contract PDFs (media/contracts/pdfs/) and generated exports
    # (media/contracts/exports/) are confidential and are never exposed as
    # unauthenticated static files; exports are streamed by the ownership-scoped
    # ContractExportView instead.
    urlpatterns += static(
        f"{settings.MEDIA_URL}profile_photos/",
        document_root=settings.MEDIA_ROOT / 'profile_photos',
    )
