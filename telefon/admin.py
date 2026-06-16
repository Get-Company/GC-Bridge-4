from django.contrib import admin
from django.urls import path

from telefon.views import zeitsteuerung_list, zeitsteuerung_detail

_default_get_urls = admin.site.get_urls


def _telefon_urls():
    return [
        path(
            "telefon/zeitsteuerung/",
            admin.site.admin_view(zeitsteuerung_list),
            name="telefon_zeitsteuerung_list",
        ),
        path(
            "telefon/zeitsteuerung/<str:service_id>/",
            admin.site.admin_view(zeitsteuerung_detail),
            name="telefon_zeitsteuerung_detail",
        ),
    ] + _default_get_urls()


admin.site.get_urls = _telefon_urls
