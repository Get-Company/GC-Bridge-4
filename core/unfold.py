from django.apps import apps
from django.contrib import admin
from django.conf import settings
from django.templatetags.static import static


def environment_callback(request):
    if settings.DEBUG:
        return ["Development", "info"]
    return ["Production", "success"]


def superuser_only(request):
    return request.user.is_superuser


def admin_model_permission(request, app_label, model_name, permission="view"):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return False

    model_admin = admin.site._registry.get(model)
    if model_admin is not None:
        permission_check = getattr(model_admin, f"has_{permission}_permission", None)
        if callable(permission_check):
            return bool(permission_check(request))

    return request.user.has_perm(f"{app_label}.{permission}_{model._meta.model_name}")


def admin_button_loader_style(_request):
    return static("core/admin/admin_button_loader.css")


def admin_button_loader_script(_request):
    return static("core/admin/admin_button_loader.js")
