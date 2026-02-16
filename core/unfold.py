from django.conf import settings


def environment_callback(request):
    if settings.DEBUG:
        return ["Development", "info"]
    return ["Production", "success"]


def superuser_only(request):
    return request.user.is_superuser
