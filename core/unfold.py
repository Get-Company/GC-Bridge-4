from django.conf import settings
from django.templatetags.static import static


def environment_callback(request):
    if settings.DEBUG:
        return ["Development", "info"]
    return ["Production", "success"]


def superuser_only(request):
    return request.user.is_superuser


def admin_button_loader_style(_request):
    return static("core/admin/admin_button_loader.css")


def admin_button_loader_script(_request):
    return static("core/admin/admin_button_loader.js")
